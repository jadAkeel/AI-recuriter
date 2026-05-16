from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

TASK_QUEUE_KEY = "task_queue:cvs"
TASK_RESULT_PREFIX = "task_result:"

ProcessFunc = Callable[..., Awaitable[dict[str, Any]]]

# In-memory fallback when Redis is unavailable
_in_memory_tasks: dict[str, dict[str, Any]] = {}
_in_memory_results: dict[str, dict[str, Any]] = {}


async def enqueue_cv_processing(
    cv_text: str | None,
    file_name: str,
    use_llm: bool = True,
    file_path: str | None = None,
    task_id: str | None = None,
) -> str:
    task_id = task_id or str(uuid.uuid4())
    task = {
        "task_id": task_id,
        "cv_text": cv_text,
        "file_name": file_name,
        "use_llm": use_llm,
        "file_path": file_path,
        "status": "queued",
    }
    r = await get_redis()
    if r:
        await r.lpush(TASK_QUEUE_KEY, json.dumps(task))
    else:
        logger.warning("Redis not available, storing task in memory (will be lost on restart)")
        _in_memory_tasks[task_id] = task
    return task_id


async def get_task_result(task_id: str) -> dict[str, Any] | None:
    r = await get_redis()
    if r:
        result = await r.get(f"{TASK_RESULT_PREFIX}{task_id}")
        return json.loads(result) if result else None
    return _in_memory_results.get(task_id)


async def run_cv_worker(process_func: ProcessFunc) -> None:
    r = await get_redis()
    if r is None:
        logger.warning("Redis not available, CV worker starting with in-memory queue only")
        async def _process_in_memory():
            while True:
                task_keys = list(_in_memory_tasks.keys())
                for task_id in task_keys:
                    task = _in_memory_tasks.pop(task_id, None)
                    if task is None:
                        continue
                    try:
                        result = await process_func(
                            cv_text=task.get("cv_text"),
                            file_name=task["file_name"],
                            use_llm=task.get("use_llm", True),
                            file_path=task.get("file_path"),
                        )
                        result["task_id"] = task_id
                        result["status"] = "completed"
                        _in_memory_results[task_id] = result
                    except Exception as e:
                        logger.error(f"CV task failed: {e}", extra={"task_id": task_id})
                        _in_memory_results[task_id] = {"task_id": task_id, "status": "failed", "error": str(e)}
                await asyncio.sleep(1)
        await _process_in_memory()
        return

    logger.info("CV queue worker started")
    while True:
        try:
            popped = await r.brpop(TASK_QUEUE_KEY, timeout=5)
            if popped is None:
                continue
            _, task_data = popped

            task = json.loads(task_data)
            task_id = task["task_id"]
            logger.info("Processing CV task", extra={"task_id": task_id, "file_name": task["file_name"]})

            try:
                result = await process_func(
                    cv_text=task.get("cv_text"),
                    file_name=task["file_name"],
                    use_llm=task.get("use_llm", True),
                    file_path=task.get("file_path"),
                )
                result["task_id"] = task_id
                result["status"] = "completed"

                await r.setex(f"{TASK_RESULT_PREFIX}{task_id}", 3600, json.dumps(result))

                await r.publish("cv:notifications", json.dumps({
                    "type": "cv_processed",
                    "task_id": task_id,
                    "candidate_id": result.get("candidate_id"),
                    "full_name": result.get("full_name"),
                    "email": result.get("email"),
                    "skills": result.get("skills", []),
                    "status": "completed",
                }))

            except Exception as e:
                logger.error(f"CV task failed: {e}", extra={"task_id": task_id})
                await r.setex(
                    f"{TASK_RESULT_PREFIX}{task_id}",
                    3600,
                    json.dumps({"task_id": task_id, "status": "failed", "error": str(e)}),
                )
                await r.publish("cv:notifications", json.dumps({
                    "type": "cv_failed",
                    "task_id": task_id,
                    "error": str(e),
                    "status": "failed",
                }))

        except Exception as e:
            logger.error(f"CV worker error: {e}")
            await asyncio.sleep(1)
