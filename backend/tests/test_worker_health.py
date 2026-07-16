import json
import time
from pathlib import Path

from app.worker_health import worker_health_status, write_worker_health_state


def test_worker_health_is_unhealthy_without_success_state(monkeypatch, tmp_path: Path):
    path = tmp_path / "worker.json"
    monkeypatch.setenv("WORKER_HEALTH_STATE_PATH", str(path))

    assert worker_health_status(max_age_seconds=30)["healthy"] is False


def test_worker_health_reports_recent_success(monkeypatch, tmp_path: Path):
    path = tmp_path / "worker.json"
    monkeypatch.setenv("WORKER_HEALTH_STATE_PATH", str(path))

    write_worker_health_state(last_success=int(time.time()), last_error=None, result={"ok": 1})

    status = worker_health_status(max_age_seconds=30)
    assert status["healthy"] is True
    assert status["lagSeconds"] <= 2
    assert json.loads(path.read_text())["result"] == {"ok": 1}


def test_worker_health_reports_stale_success(monkeypatch, tmp_path: Path):
    path = tmp_path / "worker.json"
    monkeypatch.setenv("WORKER_HEALTH_STATE_PATH", str(path))
    path.write_text(json.dumps({"lastSuccess": int(time.time()) - 120, "lastError": None}))

    status = worker_health_status(max_age_seconds=30)
    assert status["healthy"] is False
    assert status["reason"] == "worker success is stale"
