"""FastAPI bridge: n8n -> MCP client -> TrainGuard MCP tools."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import uvicorn

load_dotenv()

from trainguard.bridge.mcp_gateway import (
    begin_trace,
    call_tool,
    clear_event_log,
    get_event_log,
    get_trace,
    list_tool_schemas,
    list_tools,
)
from trainguard.llm_gemini import (
    decide_with_gemini,
    gemini_enabled,
    gemini_mcp_agent_enabled,
    run_gemini_mcp_agent,
)

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"

app = FastAPI(
    title="TrainGuard Bridge",
    version="0.6.0",
    description="HTTP façade for n8n that invokes TrainGuard exclusively via MCP.",
)


class StartBody(BaseModel):
    max_epochs: int = 6
    lr: float = 0.01
    train_size: int = 2000
    val_size: int = 1000
    batch_size: int = 64
    seed: int = 42
    dataset: str = "auto"
    dataset_path: str = ""
    dataset_url: str = ""
    image_size: int = 0


class FaultBody(BaseModel):
    kind: str = Field(default="nan_loss", description="nan_loss | exploding_lr | stall")


class AdvanceBody(BaseModel):
    n: int = 1


class ActionBody(BaseModel):
    action: str
    reason: str = ""


class RunBody(BaseModel):
    webhook_url: str
    bridge_base_url: str = ""
    dataset: str = "auto"
    kind: str = "nan_loss"
    mode: str = "demo"


def _fire_n8n_webhook(url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return


def _with_mcp_meta(payload: Any, tool: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        out = dict(payload)
    else:
        out = {"result": payload}
    trace = get_trace()
    tools = [t["tool"] for t in trace]
    story = " → ".join(["n8n", "bridge", *[f"MCP:{t}" for t in tools]])
    out["called_via_mcp"] = True
    out["mcp_tools_called"] = trace
    out["mcp_story"] = story
    out["mcp_dashboard"] = "http://127.0.0.1:8787/dashboard"
    out["_meta"] = {
        "via": "mcp",
        "tool": tool,
        "integration": "n8n -> bridge -> MCP Client -> TrainGuard tools",
        "mcp_tools_called": trace,
        "mcp_story": story,
    }
    return out


@app.middleware("http")
async def mcp_trace_middleware(request: Request, call_next):
    begin_trace(source=f"n8n/http:{request.url.path}")
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_PATH.read_text(encoding="utf-8"))


@app.get("/mcp-events")
async def mcp_events() -> dict[str, Any]:
    events = get_event_log()
    return {
        "count": len(events),
        "events": events,
        "integration": "n8n -> bridge -> MCP Client -> TrainGuard tools",
    }


@app.post("/mcp-events/clear")
async def mcp_events_clear() -> dict[str, str]:
    clear_event_log()
    return {"status": "cleared"}


@app.get("/config")
async def dashboard_config() -> dict[str, Any]:
    from trainguard.engine import available_datasets

    return {
        "n8n_webhook_url": os.getenv("N8N_WEBHOOK_URL", "").strip(),
        "bridge_public_url": os.getenv("BRIDGE_PUBLIC_URL", "").strip(),
        "datasets": available_datasets(),
        "kinds": ["nan_loss", "exploding_lr", "stall"],
        "modes": ["demo", "analyze", "inject"],
    }


@app.get("/live")
async def live() -> dict[str, Any]:
    """Dashboard snapshot — reads state without recording a MCP tool call."""
    from trainguard.engine import get_status

    state = get_status()
    metrics = state.get("metrics") or []
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "epoch": state.get("epoch"),
        "max_epochs": state.get("max_epochs"),
        "lr": state.get("lr"),
        "fault": state.get("fault"),
        "best_acc": state.get("best_acc"),
        "best_loss": state.get("best_loss"),
        "dataset": state.get("dataset"),
        "last_action": state.get("last_action"),
        "recovery": state.get("recovery_report"),
        "metrics": metrics[-8:],
        "updated_at": state.get("updated_at"),
    }


@app.post("/run")
async def run_from_dashboard(body: RunBody) -> dict[str, Any]:
    """Fire the n8n webhook so the canvas stays the orchestrator."""
    webhook = body.webhook_url.strip()
    if not webhook.startswith(("http://", "https://")):
        return {"ok": False, "error": "webhook_url must be http(s)"}
    payload = {
        "mode": body.mode or "demo",
        "kind": body.kind or "nan_loss",
        "dataset": body.dataset or "auto",
        "bridge_base_url": (
            body.bridge_base_url.strip()
            or os.getenv("BRIDGE_PUBLIC_URL", "").strip()
        ),
    }
    thread = threading.Thread(
        target=_fire_n8n_webhook,
        args=(webhook, payload),
        daemon=True,
    )
    thread.start()
    return {
        "ok": True,
        "started": True,
        "payload": payload,
        "message": "Webhook enviado a n8n. El dashboard mostrará el proceso vía MCP.",
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    tools = await list_tools()
    return {
        "status": "ok",
        "service": "trainguard-bridge",
        "mcp": "connected",
        "dashboard": "http://127.0.0.1:8787/dashboard",
        "message": "n8n reaches TrainGuard only through MCP tool calls",
        "tools": tools,
    }


@app.get("/status")
async def status() -> dict[str, Any]:
    data = await call_tool("get_training_status")
    return _with_mcp_meta(data, "get_training_status")


@app.get("/datasets")
async def datasets() -> dict[str, Any]:
    data = await call_tool("list_datasets")
    return _with_mcp_meta(data, "list_datasets")


@app.post("/start")
async def start(body: StartBody | None = None) -> dict[str, Any]:
    body = body or StartBody()
    data = await call_tool(
        "start_training",
        {
            "max_epochs": body.max_epochs,
            "lr": body.lr,
            "train_size": body.train_size,
            "val_size": body.val_size,
            "batch_size": body.batch_size,
            "seed": body.seed,
            "dataset": body.dataset,
            "dataset_path": body.dataset_path,
            "dataset_url": body.dataset_url,
            "image_size": body.image_size,
        },
    )
    return _with_mcp_meta(data, "start_training")


@app.post("/advance")
async def advance(body: AdvanceBody | None = None) -> dict[str, Any]:
    body = body or AdvanceBody()
    data = await call_tool("advance_epochs", {"n": body.n})
    return _with_mcp_meta(data, "advance_epochs")


@app.post("/inject-fault")
async def inject_fault(body: FaultBody | None = None) -> dict[str, Any]:
    """Arm a fault only — n8n decides when to train the broken epoch."""
    body = body or FaultBody()
    data = await call_tool("inject_fault", {"kind": body.kind})
    return _with_mcp_meta(data, "inject_fault")


@app.get("/metrics")
async def metrics(limit: int = 5) -> dict[str, Any]:
    data = await call_tool("get_latest_metrics", {"limit": limit})
    return _with_mcp_meta(data, "get_latest_metrics")


@app.get("/checkpoints")
async def checkpoints() -> dict[str, Any]:
    data = await call_tool("list_checkpoints")
    return _with_mcp_meta(data, "list_checkpoints")


@app.get("/compare")
async def compare() -> dict[str, Any]:
    data = await call_tool("compare_recovery")
    return _with_mcp_meta(data, "compare_recovery")


@app.post("/analyze")
async def analyze() -> dict[str, Any]:
    data = await call_tool("analyze_training")
    return _with_mcp_meta(data, "analyze_training")


@app.post("/execute")
async def execute(body: ActionBody) -> dict[str, Any]:
    data = await call_tool(
        "apply_recovery_action",
        {"action": body.action, "reason": body.reason},
    )
    return _with_mcp_meta(data, "apply_recovery_action")


@app.post("/analyze-and-apply")
async def analyze_and_apply() -> dict[str, Any]:
    """n8n path: Gemini calls MCP tools (or legacy/heuristic fallback)."""
    status_data = await call_tool("get_training_status")
    if not status_data.get("metrics"):
        await call_tool(
            "start_training",
            {"max_epochs": 6, "lr": 0.01, "train_size": 2000, "val_size": 1000},
        )
        await call_tool("advance_epochs", {"n": 2})
        status_data = await call_tool("get_training_status")

    # Default: Gemini is an MCP client (function calling → call_tool).
    if gemini_enabled() and gemini_mcp_agent_enabled():
        agent = await run_gemini_mcp_agent(
            call_tool=call_tool,
            list_tool_schemas=list_tool_schemas,
        )
        decision = agent["decision"]
        state = agent.get("state") or await call_tool("get_training_status")
        data = {
            "decision": {
                "run_id": state.get("run_id") or status_data.get("run_id"),
                "action": decision["action"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "evidence": decision["evidence"],
                "status": state.get("status"),
                "fault": state.get("fault"),
                "decided_by": decision.get("decided_by"),
                "model": decision.get("model"),
                "llm_uses_mcp": True,
                "gemini_requested_mcp_tools": decision.get(
                    "gemini_requested_mcp_tools", []
                ),
            },
            "applied": bool(agent.get("applied")),
            "gemini_mcp_rounds": agent.get("gemini_mcp_rounds", 0),
            "state": {
                "run_id": state.get("run_id"),
                "status": state.get("status"),
                "epoch": state.get("epoch"),
                "lr": state.get("lr"),
                "fault": state.get("fault"),
                "last_action": state.get("last_action"),
            },
        }
        return _with_mcp_meta(data, "gemini_mcp_agent")

    # Legacy: bridge prefetches MCP context; Gemini only returns JSON; bridge applies.
    if gemini_enabled():
        metrics = await call_tool("get_latest_metrics", {"limit": 5})
        checkpoints = await call_tool("list_checkpoints")
        decision = decide_with_gemini(
            {
                "status": status_data,
                "latest_metrics": metrics,
                "checkpoints": checkpoints,
            }
        )
        applied = False
        state = status_data
        if decision["confidence"] >= 0.75 and decision["action"] != "alert_only":
            state = await call_tool(
                "apply_recovery_action",
                {"action": decision["action"], "reason": decision["reason"]},
            )
            applied = True
        elif decision["action"] == "alert_only":
            state = await call_tool(
                "apply_recovery_action",
                {"action": "alert_only", "reason": decision["reason"]},
            )
        data = {
            "decision": {
                "run_id": status_data.get("run_id"),
                "action": decision["action"],
                "confidence": decision["confidence"],
                "reason": decision["reason"],
                "evidence": decision["evidence"],
                "status": status_data.get("status"),
                "fault": status_data.get("fault"),
                "decided_by": decision.get("decided_by"),
                "model": decision.get("model"),
                "llm_uses_mcp": False,
            },
            "applied": applied,
            "state": {
                "run_id": state.get("run_id"),
                "status": state.get("status"),
                "epoch": state.get("epoch"),
                "lr": state.get("lr"),
                "fault": state.get("fault"),
                "last_action": state.get("last_action"),
            },
        }
        return _with_mcp_meta(data, "gemini+mcp_apply")

    data = await call_tool("analyze_and_apply_recovery")
    if isinstance(data, dict) and "decision" in data:
        data["decision"]["decided_by"] = "heuristic"
        data["decision"]["llm_uses_mcp"] = False
    return _with_mcp_meta(data, "analyze_and_apply_recovery")


def main() -> None:
    uvicorn.run(
        "trainguard.bridge.app:app",
        host="0.0.0.0",
        port=8787,
        reload=False,
    )


if __name__ == "__main__":
    main()
