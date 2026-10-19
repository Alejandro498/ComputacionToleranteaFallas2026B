"""Toy training loop + fault injection + recovery actions (shared by MCP and bridge)."""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from trainguard.state import append_history, load_state, save_state


def start_training(max_epochs: int = 12, lr: float = 0.01) -> dict[str, Any]:
    state = load_state()
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    state.update(
        {
            "run_id": run_id,
            "status": "running",
            "epoch": 0,
            "max_epochs": max_epochs,
            "lr": lr,
            "best_loss": None,
            "metrics": [],
            "checkpoints": [],
            "fault": None,
            "last_action": None,
        }
    )
    append_history(state, "start_training", {"run_id": run_id, "lr": lr})
    return save_state(state)


def stop_training(reason: str = "manual_stop") -> dict[str, Any]:
    state = load_state()
    state["status"] = "stopped"
    append_history(state, "stop_training", {"reason": reason})
    state["last_action"] = {"action": "stop_training", "reason": reason}
    return save_state(state)


def inject_fault(kind: str = "nan_loss") -> dict[str, Any]:
    """Inject a training fault. kinds: nan_loss | exploding_lr | stall."""
    state = load_state()
    if state.get("status") not in {"running", "degraded"}:
        start_training()
        state = load_state()
    state["fault"] = kind
    state["status"] = "degraded"
    append_history(state, "inject_fault", {"kind": kind})
    return save_state(state)


def _simulate_epoch(state: dict[str, Any]) -> dict[str, Any]:
    epoch = int(state.get("epoch", 0)) + 1
    lr = float(state.get("lr", 0.01))
    fault = state.get("fault")

    # Healthy curve: decreasing loss with noise
    base = 1.2 * math.exp(-0.35 * (epoch - 1)) + 0.08
    loss = base + random.uniform(-0.02, 0.02)
    acc = min(0.98, 0.55 + 0.04 * epoch + random.uniform(-0.01, 0.01))

    if fault == "nan_loss" and epoch >= 3:
        loss = float("nan")
        acc = 0.0
    elif fault == "exploding_lr":
        lr = max(lr, 0.5)
        loss = base * (8 + epoch)
        acc = max(0.1, acc - 0.2)
        state["lr"] = lr
    elif fault == "stall" and epoch >= 3:
        loss = 0.85 + random.uniform(-0.01, 0.01)
        acc = 0.62

    metric = {
        "epoch": epoch,
        "loss": None if (isinstance(loss, float) and math.isnan(loss)) else round(loss, 5),
        "loss_raw": "NaN" if (isinstance(loss, float) and math.isnan(loss)) else round(loss, 5),
        "accuracy": round(acc, 5),
        "lr": lr,
        "fault": fault,
    }
    state["epoch"] = epoch
    state.setdefault("metrics", []).append(metric)

    is_nan = isinstance(loss, float) and math.isnan(loss)
    if not is_nan:
        best = state.get("best_loss")
        if best is None or loss < best:
            state["best_loss"] = round(loss, 5)
            ckpt = {
                "name": f"checkpoint_epoch_{epoch}.pt",
                "epoch": epoch,
                "loss": round(loss, 5),
                "accuracy": round(acc, 5),
            }
            state.setdefault("checkpoints", []).append(ckpt)

    if epoch >= int(state.get("max_epochs", 12)) and state.get("status") == "running":
        state["status"] = "completed"

    return metric


def advance_epochs(n: int = 1) -> dict[str, Any]:
    state = load_state()
    if state.get("status") not in {"running", "degraded", "recovering"}:
        if state.get("status") == "idle":
            state = start_training()
        else:
            return state
    for _ in range(max(1, n)):
        if state.get("epoch", 0) >= state.get("max_epochs", 12):
            break
        _simulate_epoch(state)
    append_history(state, "advance_epochs", {"n": n, "epoch": state.get("epoch")})
    return save_state(state)


def get_status() -> dict[str, Any]:
    return load_state()


def get_latest_metrics(limit: int = 5) -> dict[str, Any]:
    state = load_state()
    metrics = state.get("metrics", [])[-limit:]
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "fault": state.get("fault"),
        "metrics": metrics,
    }


def list_checkpoints() -> dict[str, Any]:
    state = load_state()
    return {
        "run_id": state.get("run_id"),
        "checkpoints": state.get("checkpoints", []),
        "best_loss": state.get("best_loss"),
    }


def analyze_and_recommend() -> dict[str, Any]:
    """Heuristic 'agent brain' — same decision shape an LLM+MCP would return."""
    state = load_state()
    metrics = state.get("metrics", [])
    if not metrics:
        state = advance_epochs(3)
        metrics = state.get("metrics", [])

    latest = metrics[-1]
    evidence: list[str] = []
    for m in metrics[-4:]:
        evidence.append(
            f"epoch={m['epoch']} loss={m['loss_raw']} acc={m['accuracy']} lr={m['lr']}"
        )

    loss_raw = latest.get("loss_raw")
    fault = state.get("fault") or latest.get("fault")

    if loss_raw == "NaN" or fault == "nan_loss":
        action = "rollback_checkpoint"
        confidence = 0.93
        reason = "Loss became NaN; rollback to last healthy checkpoint and clear fault."
    elif fault == "exploding_lr" or float(latest.get("lr", 0)) >= 0.2:
        action = "reduce_lr_and_resume"
        confidence = 0.9
        reason = "Learning rate too high / exploding loss; reduce LR and resume."
    elif fault == "stall":
        recent = metrics[-3:]
        if len(recent) >= 3:
            losses = [m["loss"] for m in recent if m["loss"] is not None]
            if len(losses) >= 3 and max(losses) - min(losses) < 0.03:
                action = "reduce_lr_and_resume"
                confidence = 0.78
                reason = "Training stalled; reduce LR and continue from current state."
            else:
                action = "alert_only"
                confidence = 0.6
                reason = "Possible stall; monitor one more window."
        else:
            action = "alert_only"
            confidence = 0.55
            reason = "Insufficient metrics to confirm stall."
    elif state.get("status") == "running":
        action = "alert_only"
        confidence = 0.7
        reason = "Training looks healthy; no recovery needed."
    else:
        action = "alert_only"
        confidence = 0.5
        reason = f"Status={state.get('status')}; no automatic recovery selected."

    decision = {
        "run_id": state.get("run_id"),
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
        "status": state.get("status"),
        "fault": fault,
        "latest_metric": latest,
    }
    return decision


def apply_action(action: str, reason: str = "") -> dict[str, Any]:
    state = load_state()
    action = action.strip()

    if action == "alert_only":
        state["last_action"] = {"action": action, "reason": reason}
        append_history(state, "apply_action", {"action": action, "reason": reason})
        return save_state(state)

    if action == "stop_training":
        return stop_training(reason or "agent_stop")

    if action == "rollback_checkpoint":
        ckpts = state.get("checkpoints", [])
        if not ckpts:
            # Create a synthetic healthy checkpoint if none exist
            ckpts = [{"name": "checkpoint_epoch_2.pt", "epoch": 2, "loss": 0.55, "accuracy": 0.7}]
            state["checkpoints"] = ckpts
        best = ckpts[-1]
        state["epoch"] = best["epoch"]
        state["fault"] = None
        state["status"] = "recovering"
        state["lr"] = min(float(state.get("lr", 0.01)), 0.01)
        state["metrics"].append(
            {
                "epoch": best["epoch"],
                "loss": best["loss"],
                "loss_raw": best["loss"],
                "accuracy": best["accuracy"],
                "lr": state["lr"],
                "fault": None,
                "note": "restored_from_checkpoint",
            }
        )
        state["status"] = "running"
        state["last_action"] = {
            "action": action,
            "reason": reason,
            "checkpoint": best["name"],
        }
        append_history(state, "rollback_checkpoint", {"checkpoint": best})
        return save_state(state)

    if action == "reduce_lr_and_resume":
        old_lr = float(state.get("lr", 0.01))
        state["lr"] = round(old_lr * 0.1, 6)
        state["fault"] = None
        state["status"] = "running"
        state["last_action"] = {
            "action": action,
            "reason": reason,
            "old_lr": old_lr,
            "new_lr": state["lr"],
        }
        append_history(
            state,
            "reduce_lr_and_resume",
            {"old_lr": old_lr, "new_lr": state["lr"]},
        )
        return save_state(state)

    state["last_action"] = {"action": "unknown", "requested": action, "reason": reason}
    append_history(state, "unknown_action", {"action": action})
    return save_state(state)


def analyze_and_apply() -> dict[str, Any]:
    decision = analyze_and_recommend()
    # Auto-apply only when confident enough (fault-tolerance policy)
    applied = False
    result_state = load_state()
    if decision["confidence"] >= 0.75 and decision["action"] != "alert_only":
        result_state = apply_action(decision["action"], decision["reason"])
        applied = True
    elif decision["action"] == "alert_only":
        result_state = apply_action("alert_only", decision["reason"])

    return {
        "decision": decision,
        "applied": applied,
        "state": {
            "run_id": result_state.get("run_id"),
            "status": result_state.get("status"),
            "epoch": result_state.get("epoch"),
            "lr": result_state.get("lr"),
            "fault": result_state.get("fault"),
            "last_action": result_state.get("last_action"),
        },
    }
