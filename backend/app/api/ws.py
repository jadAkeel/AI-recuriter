from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.redis import get_redis
from app.models.interview import InterviewSession as InterviewSessionModel
from app.services.voice_service import get_voice_service

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store for WebRTC peer connections per session
_webrtc_sessions: dict[str, dict[str, object]] = {}


@router.websocket("/ws/cv-notifications")
async def cv_notifications(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected")

    r = await get_redis()
    if r is None:
        await websocket.send_json({"type": "error", "message": "Redis not available"})
        await websocket.close()
        return

    pubsub = r.pubsub()
    await pubsub.subscribe("cv:notifications")

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json(data)
            else:
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await pubsub.unsubscribe("cv:notifications")


@router.websocket("/ws/interview/{session_id}")
async def interview_chat(websocket: WebSocket, session_id: str):
    await websocket.accept()
    _webrtc_sessions[session_id] = {"ws": websocket}
    logger.info("Interview WebSocket connected", extra={"session_id": session_id})

    async for db_session in get_db_session():
        stmt = select(InterviewSessionModel).where(InterviewSessionModel.id == session_id)
        result = await db_session.execute(stmt)
        interview = result.scalar_one_or_none()
        if interview is None:
            await websocket.send_json({"type": "error", "message": "Interview session not found"})
            await websocket.close()
            return

        voice_svc = get_voice_service()
        questions = interview.questions or []
        total = len(questions)
        answers_count = len(interview.answers or [])

        if answers_count >= total:
            scores = [e["score"] for e in (interview.evaluations or [])]
            avg = round(sum(scores) / len(scores), 4) if scores else 0
            await websocket.send_json({
                "type": "complete",
                "session_id": session_id,
                "average_score": avg,
                "total_questions": total,
                "answered": answers_count,
            })
            await websocket.close()
            return

        # Send first unanswered question
        if answers_count < total:
            q = questions[answers_count]
            await websocket.send_json({
                "type": "question",
                "question_id": q["id"],
                "skill": q.get("skill", "general"),
                "question": q["question"],
                "difficulty": q.get("difficulty", "mid"),
                "category": q.get("category", "technical"),
                "question_number": answers_count + 1,
                "total": total,
                "hint": q.get("expected_answer_hint", ""),
            })

        try:
            while True:
                raw = await websocket.receive_text()
                data = json.loads(raw)

                msg_type = data.get("type", "")

                if msg_type == "webrtc_offer":
                    target = data.get("target", "")
                    if target and _webrtc_sessions.get(target):
                        await _webrtc_sessions[target]["ws"].send_json(data)
                    else:
                        await websocket.send_json({"type": "webrtc_offer", "sdp": data.get("sdp", "")})
                    continue

                if msg_type == "webrtc_answer":
                    target = data.get("target", "")
                    if target and _webrtc_sessions.get(target):
                        await _webrtc_sessions[target]["ws"].send_json(data)
                    continue

                if msg_type == "webrtc_ice":
                    target = data.get("target", "")
                    if target and _webrtc_sessions.get(target):
                        await _webrtc_sessions[target]["ws"].send_json(data)
                    continue

                if msg_type == "voice_answer":
                    audio_b64 = data.get("audio", "")
                    q_id = data.get("question_id", "")
                    q_text = data.get("question_text", "")
                    skill = data.get("skill", "general")

                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                        result = await voice_svc.process_audio(
                            audio_data=audio_bytes,
                            session_id=session_id,
                            question_id=q_id,
                            question_text=q_text,
                            skill=skill,
                        )
                        resp = {
                            "type": "voice_evaluation",
                            "transcript": result["transcript"],
                            "score": result["score"],
                            "feedback": result["feedback"],
                            "language_detected": result.get("language_detected", "english"),
                        }
                        if result.get("audio"):
                            resp["audio"] = base64.b64encode(result["audio"]).decode("utf-8")
                        await websocket.send_json(resp)
                    except Exception as e:
                        logger.error(f"Voice answer processing failed: {e}")
                        await websocket.send_json({"type": "error", "message": f"Voice processing failed: {str(e)}"})
                    continue

                if msg_type != "answer":
                    await websocket.send_json({"type": "error", "message": "Expected 'answer' type"})
                    continue

                question_id = data.get("question_id", "")
                answer_text = data.get("answer", "")

                if not answer_text.strip():
                    await websocket.send_json({"type": "error", "message": "Answer cannot be empty"})
                    continue

                # Find the question index
                q_idx = next((i for i, q in enumerate(questions) if q["id"] == question_id), -1)
                if q_idx < 0 or q_idx != answers_count:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Expected question #{answers_count + 1}, got #{q_idx + 1}",
                    })
                    continue

                # Evaluate answer using existing interview service
                from app.services.enhanced_interview import get_enhanced_interview_service
                svc = get_enhanced_interview_service()
                try:
                    result = await svc.submit_answer(
                        db_session, session_id, question_id, answer_text,
                    )
                except Exception as e:
                    logger.error(f"Answer evaluation failed: {e}")
                    await websocket.send_json({"type": "error", "message": f"Evaluation failed: {str(e)}"})
                    continue

                await websocket.send_json({
                    "type": "evaluation",
                    "question_id": question_id,
                    "score": result["score"],
                    "feedback": result["feedback"],
                    "strengths": result.get("strengths", []),
                    "weaknesses": result.get("weaknesses", []),
                    "language_detected": result.get("language_detected", "english"),
                })

                answers_count += 1

                if answers_count >= total:
                    # Interview complete
                    scores = [e["score"] for e in (interview.evaluations or [])]
                    avg = round(sum(scores) / len(scores), 4) if scores else 0
                    await websocket.send_json({
                        "type": "complete",
                        "session_id": session_id,
                        "average_score": avg,
                        "total_questions": total,
                        "answered": answers_count,
                    })
                    break

                # Send next question
                q = questions[answers_count]
                await websocket.send_json({
                    "type": "question",
                    "question_id": q["id"],
                    "skill": q.get("skill", "general"),
                    "question": q["question"],
                    "difficulty": q.get("difficulty", "mid"),
                    "category": q.get("category", "technical"),
                    "question_number": answers_count + 1,
                    "total": total,
                    "hint": q.get("expected_answer_hint", ""),
                })

        except WebSocketDisconnect:
            logger.info("Interview WebSocket disconnected", extra={"session_id": session_id})
        except Exception as e:
            logger.error(f"Interview WebSocket error: {e}", extra={"session_id": session_id})
            try:
                await websocket.send_json({"type": "error", "message": f"Server error: {str(e)}"})
            except Exception:
                pass
        finally:
            _webrtc_sessions.pop(session_id, None)
