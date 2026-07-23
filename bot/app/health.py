import json
import os
import time
from pathlib import Path

DEFAULT_STATE_PATH = "/run/moyin-bot/health.json"
DEFAULT_MAX_AGE_SECONDS = 120


def write_bot_heartbeat(
    path: str | None = None,
    *,
    telegram_healthy: bool = True,
    api_healthy: bool = True,
) -> None:
    state_path = Path(path or os.getenv("BOT_HEALTH_STATE_PATH", DEFAULT_STATE_PATH))
    temporary_path = state_path.with_name(f".{state_path.name}.tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "healthy": telegram_healthy and api_healthy,
                "telegramHealthy": telegram_healthy,
                "apiHealthy": api_healthy,
                "checkedAt": time.time(),
            }
        ),
        encoding="utf-8",
    )
    temporary_path.replace(state_path)


def check_bot_health(
    path: str | None = None,
    *,
    max_age_seconds: int | None = None,
) -> None:
    state_path = Path(path or os.getenv("BOT_HEALTH_STATE_PATH", DEFAULT_STATE_PATH))
    max_age = max_age_seconds or int(
        os.getenv("BOT_HEALTH_MAX_AGE_SECONDS", str(DEFAULT_MAX_AGE_SECONDS))
    )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        checked_at = float(state["checkedAt"])
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("Bot heartbeat is missing or invalid") from exc
    if (
        state.get("healthy") is not True
        or state.get("telegramHealthy") is not True
        or state.get("apiHealthy") is not True
        or time.time() - checked_at > max_age
    ):
        raise SystemExit("Bot heartbeat is stale")
