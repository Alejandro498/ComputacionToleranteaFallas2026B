"""Shared training run state persisted as JSON for MCP + HTTP bridge."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
STATE_FILE = RUNS_DIR / "current_run.json"
_LOCK = threading.RLock()


def _default_state() -> dict[str, Any]:
    return {
        "run_id": None,
        "status": "idle",
        "epoch": 0,
        "max_epochs": 12,
        "lr": 0.01,
        "best_loss": None,
        "metrics": [],
        "checkpoints": [],
        "fault": None,
        "last_action": None,
        "history": [],
        "updated_at": None,
    }


def ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    ensure_dirs()
    with _LOCK:
        if not STATE_FILE.exists():
            state = _default_state()
            save_state(state)
            return state
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def append_history(state: dict[str, Any], event: str, detail: dict[str, Any] | None = None) -> None:
    state.setdefault("history", []).append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "detail": detail or {},
        }
    )
