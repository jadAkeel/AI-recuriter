from __future__ import annotations

import logging
import logging.handlers
import queue
from typing import Optional

from app.core.config import settings

_LOG_QUEUE: queue.Queue[logging.LogRecord] | None = None
_LISTENER: Optional[logging.handlers.QueueListener] = None


def configure_logging() -> None:
    global _LOG_QUEUE, _LISTENER

    if _LOG_QUEUE is not None:
        return

    log_level = logging.getLevelName(settings.log_level.upper())
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.setFormatter(formatter)

    _LOG_QUEUE = queue.Queue(maxsize=10000)
    queue_handler = logging.handlers.QueueHandler(_LOG_QUEUE)
    queue_handler.setLevel(log_level)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(queue_handler)

    _LISTENER = logging.handlers.QueueListener(_LOG_QUEUE, handler, respect_handler_level=True)
    _LISTENER.start()


def shutdown_logging() -> None:
    global _LOG_QUEUE, _LISTENER

    if _LISTENER:
        _LISTENER.stop()
    _LISTENER = None
    _LOG_QUEUE = None
