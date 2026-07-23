from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

update_id_context: ContextVar[int | str | None] = ContextVar("update_id", default=None)
_original_record_factory = logging.getLogRecordFactory()
_TELEGRAM_TOKEN_PATTERN = re.compile(r"(?<=/bot)\d+:[A-Za-z0-9_-]+")
_SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _redact(value: str) -> str:
    return _TELEGRAM_TOKEN_PATTERN.sub("[REDACTED]", value)


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _original_record_factory(*args, **kwargs)
    record.update_id = update_id_context.get()
    return record


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(_SHANGHAI_TIMEZONE).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "service": "moyin-bot",
            "message": _redact(record.getMessage()),
        }
        update_id = getattr(record, "update_id", None)
        if update_id is not None:
            payload["update_id"] = update_id
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
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
    # httpx logs complete Telegram request URLs at INFO level. Those URLs
    # contain the bot credential, so suppress them. Formatter redaction remains
    # a second layer for exceptions and custom log messages.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
