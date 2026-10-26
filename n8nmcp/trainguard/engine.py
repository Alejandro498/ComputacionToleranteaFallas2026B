"""TrainGuard engine: real MNIST training, controlled faults, checkpoint recovery."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from trainguard.datasets import list_datasets, resolve_dataset
from trainguard.state import RUNS_DIR, append_history, load_state, save_state
from trainguard import trainer

_SESSION: dict[str, Any] | None = None
ACC_TOL = 0.005
EXPLODING_LR = 5.0
STALL_LR = 1e-12


def _clear_session() -> None:
    global _SESSION
    _SESSION = None


def _run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def _capture_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    best = state.get("best_checkpoint") or {}
    return {
        "run_id": state.get("run_id"),
        "epoch": state.get("epoch"),
        "status": state.get("status"),
        "lr": state.get("lr"),
        "best_loss": state.get("best_loss"),
        "best_acc": state.get("best_acc"),
        "best_name": best.get("name"),
        "best_path": best.get("path"),
        "best_sha256": best.get("sha256"),
        "fault": state.get("fault"),
    }


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe view — never leak tensors/weights."""
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "epoch": state.get("epoch"),
        "max_epochs": state.get("max_epochs"),
        "lr": state.get("lr"),
        "best_loss": state.get("best_loss"),
        "best_acc": state.get("best_acc"),
        "best_checkpoint": state.get("best_checkpoint"),
        "metrics": state.get("metrics", []),
        "checkpoints": state.get("checkpoints", []),
        "fault": state.get("fault"),
        "last_action": state.get("last_action"),
        "dataset": state.get("dataset"),
        "trainer": state.get("trainer"),
        "snapshot_before_fault": state.get("snapshot_before_fault"),
        "recovery_report": state.get("recovery_report"),
        "history": state.get("history", []),
        "updated_at": state.get("updated_at"),
    }


def _get_session(state: dict[str, Any]) -> dict[str, Any]:
    global _SESSION
    run_id = state.get("run_id")
    if _SESSION and _SESSION.get("run_id") == run_id:
        trainer.set_optimizer_lr(_SESSION["optimizer"], float(state.get("lr", 0.01)))
        return _SESSION

    dataset = state.get("dataset") or {}
    spec = state.get("trainer") or {}
    model, optimizer, criterion = trainer.build_model(
        float(state.get("lr", 0.01)),
        in_channels=int(dataset.get("in_channels") or spec.get("in_channels") or 1),
        num_classes=int(dataset.get("num_classes") or spec.get("num_classes") or 10),
        image_size=int(dataset.get("image_size") or spec.get("image_size") or 28),
    )
    last_ckpt = spec.get("last_ckpt")
    if last_ckpt and Path(last_ckpt).exists():
        trainer.load_checkpoint(Path(last_ckpt), model, optimizer)
        trainer.set_optimizer_lr(optimizer, float(state.get("lr", 0.01)))

    loader_spec = {
        "id": dataset.get("id") or dataset.get("resolved") or "mnist",
        "kind": dataset.get("kind") or "torchvision",
        "in_channels": dataset.get("in_channels") or 1,
        "image_size": dataset.get("image_size") or 28,
        "num_classes": dataset.get("num_classes") or 10,
        "path": dataset.get("path"),
    }
    train_loader, val_loader, _meta = trainer.build_loaders(
        loader_spec,
        train_size=int(dataset.get("train_size", 2000)),
        val_size=int(dataset.get("val_size", 1000)),
        batch_size=int(dataset.get("batch_size", 64)),
        seed=int(spec.get("seed", 42)),
    )
    _SESSION = {
        "run_id": run_id,
        "model": model,
        "optimizer": optimizer,
        "criterion": criterion,
        "train_loader": train_loader,
        "val_loader": val_loader,
    }
    return _SESSION


def start_training(
    max_epochs: int = 6,
    lr: float = 0.01,
    train_size: int = 2000,
    val_size: int = 1000,
    batch_size: int = 64,
    seed: int = 42,
    dataset: str = "auto",
    dataset_path: str = "",
    dataset_url: str = "",
    image_size: int = 0,
) -> dict[str, Any]:
    _clear_session()
    trainer.seed_everything(seed)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    ckpt_dir = _run_dir(run_id)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    resolved = resolve_dataset(
        dataset=dataset,
        dataset_path=dataset_path,
        dataset_url=dataset_url,
        image_size=image_size,
        run_id=run_id,
    )
    loader_spec = {
        "id": resolved.get("id") or resolved.get("resolved") or "mnist",
        "kind": resolved.get("kind") or "torchvision",
        "in_channels": resolved.get("in_channels") or 1,
        "image_size": resolved.get("image_size") or 28,
        "num_classes": resolved.get("num_classes") or 10,
        "path": resolved.get("path"),
    }
    train_loader, val_loader, ds_meta = trainer.build_loaders(
        loader_spec,
        train_size=train_size,
        val_size=val_size,
        batch_size=batch_size,
        seed=seed,
    )
    model, optimizer, criterion = trainer.build_model(
        lr,
        in_channels=int(ds_meta["in_channels"]),
        num_classes=int(ds_meta["num_classes"]),
        image_size=int(ds_meta["image_size"]),
    )

    state = load_state()
    state.update(
        {
            "run_id": run_id,
            "status": "running",
            "epoch": 0,
            "max_epochs": max_epochs,
            "lr": lr,
            "best_loss": None,
            "best_acc": None,
            "best_checkpoint": None,
            "metrics": [],
            "checkpoints": [],
            "fault": None,
            "last_action": None,
            "snapshot_before_fault": None,
            "recovery_report": None,
            "dataset": {
                "id": ds_meta.get("id"),
                "name": resolved.get("name"),
                "kind": ds_meta.get("kind"),
                "resolved": resolved.get("resolved"),
                "path": ds_meta.get("path"),
                "url": resolved.get("url"),
                "in_channels": ds_meta.get("in_channels"),
                "image_size": ds_meta.get("image_size"),
                "num_classes": ds_meta.get("num_classes"),
                "train_size": ds_meta.get("train_len"),
                "val_size": ds_meta.get("val_len"),
                "batch_size": batch_size,
                "requested": dataset,
            },
            "trainer": {
                "backend": "pytorch",
                "model": "TinyCNN",
                "device": "cpu",
                "seed": seed,
                "in_channels": ds_meta.get("in_channels"),
                "num_classes": ds_meta.get("num_classes"),
                "image_size": ds_meta.get("image_size"),
                "ckpt_dir": str(ckpt_dir),
                "last_ckpt": str(ckpt_dir / "last.pt"),
                "best_ckpt": str(ckpt_dir / "best.pt"),
            },
            "history": [],
        }
    )
    global _SESSION
    _SESSION = {
        "run_id": run_id,
        "model": model,
        "optimizer": optimizer,
        "criterion": criterion,
        "train_loader": train_loader,
        "val_loader": val_loader,
    }
    trainer.save_checkpoint(
        Path(state["trainer"]["last_ckpt"]),
        model,
        optimizer,
        {
            "epoch": 0,
            "val_loss": None,
            "val_acc": None,
            "lr": lr,
            "healthy": True,
            "is_best": False,
            "note": "initialized",
        },
    )
    append_history(
        state,
        "start_training",
        {
            "run_id": run_id,
            "lr": lr,
            "dataset": state["dataset"],
        },
    )
    return _public_state(save_state(state))


def available_datasets() -> dict[str, Any]:
    return list_datasets()


def stop_training(reason: str = "manual_stop") -> dict[str, Any]:
    state = load_state()
    state["status"] = "stopped"
    append_history(state, "stop_training", {"reason": reason})
    state["last_action"] = {"action": "stop_training", "reason": reason}
    return _public_state(save_state(state))


def _has_trainer(state: dict[str, Any]) -> bool:
    spec = state.get("trainer") or {}
    return bool(state.get("run_id") and spec.get("last_ckpt") and spec.get("ckpt_dir"))


def inject_fault(kind: str = "nan_loss") -> dict[str, Any]:
    """Inject a real training fault. kinds: nan_loss | exploding_lr | stall."""
    state = load_state()
    if state.get("status") not in {"running", "degraded"} or not _has_trainer(state):
        start_training()
        state = load_state()

    if not state.get("snapshot_before_fault"):
        state["snapshot_before_fault"] = _capture_snapshot(state)

    session = _get_session(state)
    if kind == "exploding_lr":
        trainer.set_optimizer_lr(session["optimizer"], EXPLODING_LR)
        state["lr"] = EXPLODING_LR
    elif kind == "stall":
        trainer.set_optimizer_lr(session["optimizer"], STALL_LR)
        state["lr"] = STALL_LR

    trainer.save_checkpoint(
        Path(state["trainer"]["last_ckpt"]),
        session["model"],
        session["optimizer"],
        {
            "epoch": state.get("epoch", 0),
            "val_loss": state.get("best_loss"),
            "val_acc": state.get("best_acc"),
            "lr": state["lr"],
            "healthy": True,
            "is_best": False,
            "note": f"fault_armed:{kind}",
        },
    )
    state["fault"] = kind
    state["status"] = "degraded"
    append_history(state, "inject_fault", {"kind": kind, "lr": state["lr"]})
    return _public_state(save_state(state))


def _run_epoch(state: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(state)
    epoch = int(state.get("epoch", 0)) + 1
    fault = state.get("fault")
    lr = float(state.get("lr", 0.01))
    trainer.set_optimizer_lr(session["optimizer"], lr)

    train_m = trainer.train_one_epoch(
        session["model"],
        session["train_loader"],
        session["optimizer"],
        session["criterion"],
        fault,
    )
    if train_m["healthy"]:
        val_m = trainer.evaluate(
            session["model"], session["val_loader"], session["criterion"]
        )
    else:
        val_m = {
            "loss": None,
            "loss_raw": "NaN",
            "accuracy": 0.0,
            "healthy": False,
            "split": "val",
        }
    healthy = bool(train_m["healthy"] and val_m["healthy"])

    metric = {
        "epoch": epoch,
        "loss": val_m["loss"],
        "loss_raw": val_m["loss_raw"],
        "accuracy": val_m["accuracy"],
        "train_loss": train_m["loss"],
        "train_loss_raw": train_m["loss_raw"],
        "train_accuracy": train_m["accuracy"],
        "lr": lr,
        "fault": fault,
        "healthy": healthy,
        "weights_finite": trainer.weights_finite(session["model"]),
    }
    state["epoch"] = epoch
    state.setdefault("metrics", []).append(metric)

    spec = state["trainer"]
    ckpt_dir = Path(spec["ckpt_dir"])
    last_info = trainer.save_checkpoint(
        Path(spec["last_ckpt"]),
        session["model"],
        session["optimizer"],
        {
            "epoch": epoch,
            "val_loss": val_m["loss"],
            "val_acc": val_m["accuracy"],
            "lr": lr,
            "healthy": healthy,
            "is_best": False,
        },
    )

    if healthy:
        is_best = state.get("best_acc") is None or val_m["accuracy"] > float(
            state["best_acc"]
        )
        epoch_info = trainer.save_checkpoint(
            ckpt_dir / f"epoch_{epoch:03d}.pt",
            session["model"],
            session["optimizer"],
            {
                "epoch": epoch,
                "val_loss": val_m["loss"],
                "val_acc": val_m["accuracy"],
                "lr": lr,
                "healthy": True,
                "is_best": is_best,
            },
        )
        state.setdefault("checkpoints", []).append(epoch_info)
        if is_best:
            best_info = trainer.save_checkpoint(
                Path(spec["best_ckpt"]),
                session["model"],
                session["optimizer"],
                {
                    "epoch": epoch,
                    "val_loss": val_m["loss"],
                    "val_acc": val_m["accuracy"],
                    "lr": lr,
                    "healthy": True,
                    "is_best": True,
                },
            )
            state["best_loss"] = val_m["loss"]
            state["best_acc"] = val_m["accuracy"]
            state["best_checkpoint"] = best_info
            epoch_info["is_best"] = True
            epoch_info["sha256_best"] = best_info["sha256"]
    else:
        state["status"] = "degraded"
        state.setdefault("checkpoints", []).append(
            {
                **last_info,
                "name": f"epoch_{epoch:03d}_broken.pt",
                "healthy": False,
                "is_best": False,
            }
        )

    if epoch >= int(state.get("max_epochs", 6)) and state.get("status") == "running":
        state["status"] = "completed"

    return metric


def advance_epochs(n: int = 1) -> dict[str, Any]:
    state = load_state()
    if not _has_trainer(state):
        state = start_training()
    if state.get("status") not in {"running", "degraded", "recovering"}:
        if state.get("status") == "idle":
            state = start_training()
        else:
            return _public_state(state)
    trained = 0
    for _ in range(max(1, n)):
        if state.get("epoch", 0) >= state.get("max_epochs", 6):
            if state.get("status") == "running":
                state["status"] = "completed"
            break
        _run_epoch(state)
        trained += 1
    append_history(
        state,
        "advance_epochs",
        {"requested": n, "trained": trained, "epoch": state.get("epoch")},
    )
    return _public_state(save_state(state))


def get_status() -> dict[str, Any]:
    return _public_state(load_state())


def get_latest_metrics(limit: int = 5) -> dict[str, Any]:
    state = load_state()
    metrics = state.get("metrics", [])[-limit:]
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "fault": state.get("fault"),
        "best_acc": state.get("best_acc"),
        "best_loss": state.get("best_loss"),
        "metrics": metrics,
    }


def list_checkpoints() -> dict[str, Any]:
    state = load_state()
    return {
        "run_id": state.get("run_id"),
        "checkpoints": state.get("checkpoints", []),
        "best_loss": state.get("best_loss"),
        "best_acc": state.get("best_acc"),
        "best_checkpoint": state.get("best_checkpoint"),
    }


def analyze_and_recommend() -> dict[str, Any]:
    """Heuristic brain — same decision shape Gemini+MCP would return."""
    state = load_state()
    metrics = state.get("metrics", [])
    if not metrics:
        return {
            "run_id": state.get("run_id"),
            "action": "alert_only",
            "confidence": 0.4,
            "reason": "No metrics yet; train at least one epoch before recovering.",
            "evidence": [],
            "status": state.get("status"),
            "fault": state.get("fault"),
            "latest_metric": None,
        }

    latest = metrics[-1]
    evidence = [
        (
            f"epoch={m['epoch']} val_loss={m['loss_raw']} val_acc={m['accuracy']} "
            f"lr={m['lr']} healthy={m.get('healthy')}"
        )
        for m in metrics[-4:]
    ]
    if state.get("best_checkpoint"):
        best = state["best_checkpoint"]
        evidence.append(
            f"best.pt epoch={best.get('epoch')} acc={best.get('accuracy')} "
            f"sha256={str(best.get('sha256') or '')[:12]}"
        )

    loss_raw = latest.get("loss_raw")
    fault = state.get("fault") or latest.get("fault")
    latest_lr = float(latest.get("lr", 0) or 0)

    if (
        loss_raw == "NaN"
        or fault == "nan_loss"
        or latest.get("healthy") is False
        or latest.get("weights_finite") is False
    ):
        action = "rollback_checkpoint"
        confidence = 0.95
        reason = "Val loss is NaN or weights are not finite; rollback to best.pt."
    elif fault == "exploding_lr" or latest_lr >= 0.5:
        action = "reduce_lr_and_resume"
        confidence = 0.9
        reason = "Learning rate exploded; reduce LR and resume from current weights."
        if latest.get("healthy") is False:
            action = "rollback_checkpoint"
            reason = "Exploding LR left the run unhealthy; rollback to best.pt."
    elif fault == "stall":
        recent = [m for m in metrics[-3:] if m.get("loss") is not None]
        if len(recent) >= 3:
            losses = [float(m["loss"]) for m in recent]
            if max(losses) - min(losses) < 0.03:
                action = "reduce_lr_and_resume"
                confidence = 0.8
                reason = "Validation loss stalled; restore a usable LR and continue."
            else:
                action = "alert_only"
                confidence = 0.6
                reason = "Possible stall; monitor one more window."
        else:
            action = "reduce_lr_and_resume"
            confidence = 0.78
            reason = "Stall fault is armed; restore LR before more epochs are wasted."
    elif state.get("status") == "running":
        action = "alert_only"
        confidence = 0.7
        reason = "Training looks healthy; no recovery needed."
    else:
        action = "alert_only"
        confidence = 0.5
        reason = f"Status={state.get('status')}; no automatic recovery selected."

    return {
        "run_id": state.get("run_id"),
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
        "status": state.get("status"),
        "fault": fault,
        "latest_metric": latest,
        "best_acc": state.get("best_acc"),
        "best_checkpoint": state.get("best_checkpoint"),
    }


def _best_healthy_checkpoint(state: dict[str, Any]) -> dict[str, Any] | None:
    best = state.get("best_checkpoint")
    if best and best.get("path") and Path(best["path"]).exists():
        return best
    for ckpt in reversed(state.get("checkpoints") or []):
        if ckpt.get("healthy") and ckpt.get("path") and Path(ckpt["path"]).exists():
            return ckpt
    return None


def apply_action(action: str, reason: str = "") -> dict[str, Any]:
    state = load_state()
    action = action.strip()

    if action == "alert_only":
        state["last_action"] = {"action": action, "reason": reason}
        append_history(state, "apply_action", {"action": action, "reason": reason})
        return _public_state(save_state(state))

    if action == "stop_training":
        return stop_training(reason or "agent_stop")

    if action == "rollback_checkpoint":
        session = _get_session(state)
        best = _best_healthy_checkpoint(state)
        if not best:
            state["last_action"] = {
                "action": action,
                "reason": "No healthy checkpoint on disk; cannot rollback.",
                "applied": False,
            }
            append_history(state, "rollback_failed", {"reason": "missing_checkpoint"})
            return _public_state(save_state(state))

        sha_before = best.get("sha256")
        blob = trainer.load_checkpoint(
            Path(best["path"]), session["model"], session["optimizer"]
        )
        restored_lr = min(float(blob.get("lr") or state.get("lr") or 0.01), 0.01)
        trainer.set_optimizer_lr(session["optimizer"], restored_lr)
        state["lr"] = restored_lr
        state["epoch"] = int(blob.get("epoch") or best.get("epoch") or 0)
        state["fault"] = None
        state["status"] = "running"

        last_info = trainer.save_checkpoint(
            Path(state["trainer"]["last_ckpt"]),
            session["model"],
            session["optimizer"],
            {
                "epoch": state["epoch"],
                "val_loss": best.get("loss"),
                "val_acc": best.get("accuracy"),
                "lr": restored_lr,
                "healthy": True,
                "is_best": False,
                "note": "restored_from_checkpoint",
            },
        )
        verify = trainer.evaluate(
            session["model"], session["val_loader"], session["criterion"]
        )
        sha_after = trainer.sha256_file(Path(best["path"]))
        state["metrics"].append(
            {
                "epoch": state["epoch"],
                "loss": verify["loss"],
                "loss_raw": verify["loss_raw"],
                "accuracy": verify["accuracy"],
                "lr": restored_lr,
                "fault": None,
                "healthy": verify["healthy"],
                "weights_finite": trainer.weights_finite(session["model"]),
                "note": "restored_from_checkpoint",
                "checkpoint": best["name"],
            }
        )
        state["last_action"] = {
            "action": action,
            "reason": reason,
            "checkpoint": best["name"],
            "checkpoint_path": best.get("path"),
            "sha256_before": sha_before,
            "sha256_after": sha_after,
            "best_file_unchanged": sha_before == sha_after,
            "reload_val_acc": verify["accuracy"],
            "reload_val_loss": verify["loss"],
            "weights_finite": trainer.weights_finite(session["model"]),
            "last_ckpt": last_info["path"],
        }
        append_history(state, "rollback_checkpoint", state["last_action"])
        return _public_state(save_state(state))

    if action == "reduce_lr_and_resume":
        session = _get_session(state)
        if not trainer.weights_finite(session["model"]):
            return apply_action(
                "rollback_checkpoint",
                (reason + " ").strip()
                + "(auto-escalated: weights were NaN, reduce_lr is not enough)",
            )
        old_lr = float(state.get("lr", 0.01))
        new_lr = round(max(old_lr * 0.1, 1e-5), 6)
        if old_lr >= EXPLODING_LR / 2:
            new_lr = 0.01
        if old_lr <= STALL_LR * 10:
            new_lr = 0.01
        trainer.set_optimizer_lr(session["optimizer"], new_lr)
        state["lr"] = new_lr
        state["fault"] = None
        state["status"] = "running"
        trainer.save_checkpoint(
            Path(state["trainer"]["last_ckpt"]),
            session["model"],
            session["optimizer"],
            {
                "epoch": state.get("epoch", 0),
                "val_loss": state.get("best_loss"),
                "val_acc": state.get("best_acc"),
                "lr": new_lr,
                "healthy": True,
                "is_best": False,
                "note": "lr_reduced",
            },
        )
        state["last_action"] = {
            "action": action,
            "reason": reason,
            "old_lr": old_lr,
            "new_lr": new_lr,
        }
        append_history(state, "reduce_lr_and_resume", state["last_action"])
        return _public_state(save_state(state))

    state["last_action"] = {
        "action": "unknown",
        "requested": action,
        "reason": reason,
    }
    append_history(state, "unknown_action", {"action": action})
    return _public_state(save_state(state))


def compare_recovery() -> dict[str, Any]:
    """Measure whether recovery kept the best result and let training continue."""
    state = load_state()
    before = state.get("snapshot_before_fault") or _capture_snapshot(state)
    latest = (state.get("metrics") or [None])[-1]
    after = _capture_snapshot(state)
    before_acc = before.get("best_acc")
    after_acc = after.get("best_acc")
    preserved_best = (
        before_acc is not None
        and after_acc is not None
        and float(after_acc) + 1e-12 >= float(before_acc) - ACC_TOL
    )
    latest_healthy = bool(latest and latest.get("healthy") and latest.get("loss") is not None)
    resumed = state.get("status") in {"running", "completed", "recovering"} and (
        latest_healthy or (state.get("last_action") or {}).get("action")
        in {"rollback_checkpoint", "reduce_lr_and_resume"}
    )
    if latest and latest.get("loss_raw") == "NaN":
        resumed = False
        latest_healthy = False

    delta = None
    if before_acc is not None and after_acc is not None:
        delta = round(float(after_acc) - float(before_acc), 5)

    report = {
        "run_id": state.get("run_id"),
        "before": before,
        "after": after,
        "latest_metric": latest,
        "last_action": state.get("last_action"),
        "best_acc_before": before_acc,
        "best_acc_after": after_acc,
        "best_acc_delta": delta,
        "preserved_best": preserved_best,
        "latest_healthy": latest_healthy,
        "resumed": resumed,
        "recovery_success": bool(preserved_best and resumed),
        "best_sha256_at_fault": before.get("best_sha256"),
        "best_sha256_now": after.get("best_sha256"),
    }
    state["recovery_report"] = report
    save_state(state)
    return report


def analyze_and_apply() -> dict[str, Any]:
    decision = analyze_and_recommend()
    applied = False
    result_state = load_state()
    if decision["confidence"] >= 0.75 and decision["action"] != "alert_only":
        result_state = apply_action(decision["action"], decision["reason"])
        applied = True
    elif decision["action"] == "alert_only":
        result_state = apply_action("alert_only", decision["reason"])

    report = compare_recovery() if result_state.get("snapshot_before_fault") else None
    return {
        "decision": decision,
        "applied": applied,
        "recovery": report,
        "state": {
            "run_id": result_state.get("run_id"),
            "status": result_state.get("status"),
            "epoch": result_state.get("epoch"),
            "lr": result_state.get("lr"),
            "fault": result_state.get("fault"),
            "best_acc": result_state.get("best_acc"),
            "best_loss": result_state.get("best_loss"),
            "last_action": result_state.get("last_action"),
        },
    }
