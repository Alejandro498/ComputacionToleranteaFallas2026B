"""FastAPI bridge: n8n -> MCP client -> TrainGuard MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import uvicorn

from trainguard.bridge.mcp_gateway import (
    begin_trace,
    call_tool,
    clear_event_log,
    get_event_log,
    get_trace,
    list_tools,
)
from trainguard.llm_gemini import decide_with_gemini, gemini_enabled

DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")

app = FastAPI(
    title="TrainGuard Bridge",
    version="0.4.0",
    description="HTTP façade for n8n that invokes TrainGuard exclusively via MCP.",
)


class StartBody(BaseModel):
    max_epochs: int = 12
    lr: float = 0.01


class FaultBody(BaseModel):
    kind: str = Field(default="nan_loss", description="nan_loss | exploding_lr | stall")


class AdvanceBody(BaseModel):
    n: int = 1


class ActionBody(BaseModel):
    action: str
    reason: str = ""


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
    return HTMLResponse(DASHBOARD_HTML)


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


@app.post("/start")
async def start(body: StartBody | None = None) -> dict[str, Any]:
    body = body or StartBody()
    data = await call_tool(
        "start_training",
        {"max_epochs": body.max_epochs, "lr": body.lr},
    )
    return _with_mcp_meta(data, "start_training")


@app.post("/advance")
async def advance(body: AdvanceBody | None = None) -> dict[str, Any]:
    body = body or AdvanceBody()
    data = await call_tool("advance_epochs", {"n": body.n})
    return _with_mcp_meta(data, "advance_epochs")


@app.post("/inject-fault")
async def inject_fault(body: FaultBody | None = None) -> dict[str, Any]:
    body = body or FaultBody()
    await call_tool("inject_fault", {"kind": body.kind})
    data = await call_tool("advance_epochs", {"n": 3})
    return _with_mcp_meta(data, "inject_fault+advance_epochs")


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
    """n8n path: gather context via MCP, decide with Gemini (or heuristic), apply via MCP."""
    status_data = await call_tool("get_training_status")
    if not status_data.get("metrics"):
        await call_tool("start_training", {"max_epochs": 12, "lr": 0.01})
        await call_tool("advance_epochs", {"n": 2})
        status_data = await call_tool("get_training_status")

    metrics = await call_tool("get_latest_metrics", {"limit": 5})
    checkpoints = await call_tool("list_checkpoints")

    if gemini_enabled():
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
