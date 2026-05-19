from __future__ import annotations

import base64
import asyncio
import inspect
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.redis import get_redis
from app.models.interview import InterviewSession as InterviewSessionModel
from app.services.auth import decode_token, get_user_by_id
from app.services.interview_analysis import analyze_completed_interview
from app.services.voice_service import get_voice_service

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory store for WebRTC peer connections per session
_webrtc_sessions: dict[str, dict[str, object]] = {}


async def _authenticate_websocket(websocket: WebSocket) -> bool:
    """
    Authenticates a websocket connection using a bearer token.
    """
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    payload = decode_token(token or "")
    user_id = payload.get("sub") if payload else None
    if payload is None or payload.get("type") != "access" or not isinstance(user_id, str):
        await websocket.close(code=1008)
        return False

    async with SessionLocal() as session:
        user = await get_user_by_id(session, user_id)
        if user is None:
            await websocket.close(code=1008)
            return False
    return True


@router.websocket("/ws/cv-notifications")
async def cv_notifications(websocket: WebSocket):
    """
    Streams CV processing task updates over websocket.
    """
    await websocket.accept()
    if not await _authenticate_websocket(websocket):
        return
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
                try:
                    data = json.loads(message["data"])
                except json.JSONDecodeError:
                    logger.warning("Invalid Redis notification payload")
                    continue
                await websocket.send_json(data)
            else:
                try:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        await pubsub.unsubscribe("cv:notifications")
        close_func = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
        if close_func:
            result = close_func()
            if inspect.isawaitable(result):
                await result


@router.websocket("/ws/interview/{session_id}")
async def interview_chat(websocket: WebSocket, session_id: str):
    """
    Handles live interview chat messages over websocket.
    """
    await websocket.accept()
    _webrtc_sessions[session_id] = {"ws": websocket}
    logger.info("Interview WebSocket connected", extra={"session_id": session_id})

    async with SessionLocal() as db_session:
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

                    try:
                        audio_bytes = base64.b64decode(audio_b64, validate=True)
                        transcript = await voice_svc.transcribe_audio(audio_bytes)
                        if not transcript.strip():
                            await websocket.send_json({"type": "error", "message": "Could not transcribe an answer"})
                            continue

                        q_idx = next((i for i, q in enumerate(questions) if q["id"] == q_id), -1)
                        if q_idx < 0 or q_idx != answers_count:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Expected question #{answers_count + 1}, got #{q_idx + 1}",
                            })
                            continue

                        from app.services.enhanced_interview import get_enhanced_interview_service
                        svc = get_enhanced_interview_service()
                        result = await svc.submit_answer(
                            db_session, session_id, q_id, transcript, use_llm=False,
                        )

                        await db_session.refresh(interview)

                        await websocket.send_json({
                            "type": "voice_evaluation",
                            "question_id": q_id,
                            "transcript": transcript,
                            "score": result["score"],
                            "feedback": result["feedback"],
                            "language_detected": result.get("language_detected", "english"),
                            "strengths": result.get("strengths", []),
                            "weaknesses": result.get("weaknesses", []),
                            "using_llm": result.get("using_llm", False),
                        })

                        answers_count += 1

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
                            asyncio.create_task(analyze_completed_interview(session_id))
                            break

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
                        })
                    except Exception:
                        logger.exception("Voice answer processing failed")
                        await websocket.send_json({"type": "error", "message": "Voice processing failed"})
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
                        db_session, session_id, question_id, answer_text, use_llm=False,
                    )
                except Exception:
                    logger.exception("Answer evaluation failed")
                    await websocket.send_json({"type": "error", "message": "Evaluation failed"})
                    continue

                await db_session.refresh(interview)

                await websocket.send_json({
                    "type": "evaluation",
                    "question_id": question_id,
                    "score": result["score"],
                    "feedback": result["feedback"],
                    "strengths": result.get("strengths", []),
                    "weaknesses": result.get("weaknesses", []),
                    "language_detected": result.get("language_detected", "english"),
                    "using_llm": result.get("using_llm", False),
                })

                answers_count += 1

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
                    asyncio.create_task(analyze_completed_interview(session_id))
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
                })

        except WebSocketDisconnect:
            logger.info("Interview WebSocket disconnected", extra={"session_id": session_id})
        except Exception:
            logger.exception("Interview WebSocket error", extra={"session_id": session_id})
            try:
                await websocket.send_json({"type": "error", "message": "Server error"})
            except Exception:
                pass
        finally:
            _webrtc_sessions.pop(session_id, None)
