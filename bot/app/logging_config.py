from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

update_id_context: ContextVar[int | str | None] = ContextVar("update_id", default=None)
_original_record_factory = logging.getLogRecordFactory()


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _original_record_factory(*args, **kwargs)
    record.update_id = update_id_context.get()
    return record


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": "moyin-bot",
            "message": record.getMessage(),
        }
        update_id = getattr(record, "update_id", None)
        if update_id is not None:
            payload["update_id"] = update_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging() -> None:
    if not getattr(logging.getLogRecordFactory(), "_moyin_bot", False):
        _record_factory._moyin_bot = True  # type: ignore[attr-defined]
        logging.setLogRecordFactory(_record_factory)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
