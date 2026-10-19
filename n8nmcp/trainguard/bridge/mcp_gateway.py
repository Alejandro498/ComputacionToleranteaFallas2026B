"""n8n reaches TrainGuard only through the MCP client (real tool calls)."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from contextvars import ContextVar
from typing import Any

from fastmcp import Client

from trainguard.mcp_server import mcp

_mcp_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar("mcp_calls", default=None)
_request_source: ContextVar[str] = ContextVar("request_source", default="unknown")

_LOCK = threading.Lock()
_EVENT_LOG: deque[dict[str, Any]] = deque(maxlen=80)


def begin_trace(source: str = "unknown") -> None:
    _mcp_calls.set([])
    _request_source.set(source)


def get_trace() -> list[dict[str, Any]]:
    return list(_mcp_calls.get() or [])


def get_event_log(limit: int = 40) -> list[dict[str, Any]]:
    with _LOCK:
        events = list(_EVENT_LOG)
    return list(reversed(events[-limit:]))


def clear_event_log() -> None:
    with _LOCK:
        _EVENT_LOG.clear()


def _record_event(entry: dict[str, Any]) -> None:
    with _LOCK:
        _EVENT_LOG.append(entry)


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Invoke an MCP tool by name and return parsed data."""
    arguments = arguments or {}
    source = _request_source.get()
    started = time.time()
    async with Client(mcp) as client:
        result = await client.call_tool(name, arguments)
        elapsed_ms = int((time.time() - started) * 1000)
        event = {
            "ts": time.strftime("%H:%M:%S"),
            "protocol": "MCP",
            "tool": name,
            "arguments": arguments,
            "ok": not result.is_error,
            "source": source,
            "elapsed_ms": elapsed_ms,
        }
        trace = _mcp_calls.get()
        if trace is not None:
            trace.append(event)
        _record_event(event)
        if result.is_error:
            raise RuntimeError(f"MCP tool '{name}' failed: {result.content}")
        if result.data is not None:
            return result.data
        if result.structured_content is not None:
            return result.structured_content
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return {"ok": True, "tool": name}


async def list_tools() -> list[str]:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        return [t.name for t in tools]


async def list_tool_schemas() -> list[dict[str, Any]]:
    """Return MCP tool name/description/input schema for LLM function calling."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        out: list[dict[str, Any]] = []
        for t in tools:
            schema = getattr(t, "input_schema", None)
            if schema is None:
                schema = getattr(t, "inputSchema", None)
            if hasattr(schema, "model_dump"):
                schema = schema.model_dump(by_alias=True, exclude_none=True)
            elif not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            out.append(
                {
                    "name": t.name,
                    "description": t.description or t.name,
                    "input_schema": schema,
                }
            )
        return out
