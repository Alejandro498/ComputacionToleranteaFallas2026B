"""Gemini as an MCP client: function-calling loop over TrainGuard tools."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv

load_dotenv()

ALLOWED_ACTIONS = {
    "alert_only",
    "rollback_checkpoint",
    "reduce_lr_and_resume",
    "stop_training",
}

# Tools Gemini may call during analyze-and-apply (n8n already started/injected).
AGENT_MCP_TOOLS = {
    "get_training_status",
    "get_latest_metrics",
    "list_checkpoints",
    "apply_recovery_action",
}

CallToolFn = Callable[[str, dict[str, Any] | None], Awaitable[Any]]
ListSchemasFn = Callable[[], Awaitable[list[dict[str, Any]]]]


def gemini_enabled() -> bool:
    if os.getenv("USE_GEMINI", "true").lower() in {"0", "false", "no"}:
        return False
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def gemini_mcp_agent_enabled() -> bool:
    """True unless GEMINI_MCP_AGENT=false (legacy JSON-only path)."""
    return os.getenv("GEMINI_MCP_AGENT", "true").lower() not in {"0", "false", "no"}


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(f"Gemini did not return JSON: {text[:300]}")
    return json.loads(match.group(0))


def _normalize_decision(data: dict[str, Any], *, model: str, decided_by: str) -> dict[str, Any]:
    action = str(data.get("action", "alert_only")).strip()
    if action not in ALLOWED_ACTIONS:
        action = "alert_only"

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    evidence = data.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = [str(evidence)]

    return {
        "action": action,
        "confidence": confidence,
        "reason": str(data.get("reason", "Decisión Gemini")),
        "evidence": [str(e) for e in evidence],
        "decided_by": decided_by,
        "model": model,
    }


def _schema_for_gemini(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    out = {k: v for k, v in schema.items() if k != "additionalProperties"}
    out.setdefault("type", "object")
    out.setdefault("properties", {})
    return out


def _args_to_dict(args: Any) -> dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    if hasattr(args, "model_dump"):
        return dict(args.model_dump(exclude_none=True))
    try:
        return dict(args)
    except (TypeError, ValueError):
        return {}


def decide_with_gemini(context: dict[str, Any]) -> dict[str, Any]:
    """Legacy path: ask Gemini for a recovery decision given pre-fetched MCP context."""
    from google import genai

    api_key = os.environ["GEMINI_API_KEY"].strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    client = genai.Client(api_key=api_key)

    prompt = f"""Eres el agente de tolerancia a fallas de TrainGuard (MNIST + PyTorch).
Analiza el contexto del entrenamiento real y decide UNA acción.

Acciones permitidas:
- alert_only
- rollback_checkpoint
- reduce_lr_and_resume
- stop_training

Reglas:
- Si val_loss es NaN, weights_finite=false o fault=nan_loss → rollback_checkpoint (carga best.pt).
- Si LR muy alto o fault=exploding_lr → reduce_lr_and_resume (o rollback si el run ya está unhealthy).
- Si stall → reduce_lr_and_resume.
- Si todo sano → alert_only.
- No inventes métricas. El rollback debe preservar best_acc.
- Responde SOLO JSON válido, sin markdown.

Formato exacto:
{{
  "action": "...",
  "confidence": 0.0,
  "reason": "...",
  "evidence": ["...", "..."]
}}

Contexto (obtenido vía tools MCP):
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    response = client.models.generate_content(model=model, contents=prompt)
    text = (response.text or "").strip()
    data = _extract_json(text)
    return _normalize_decision(data, model=model, decided_by="gemini")


async def run_gemini_mcp_agent(
    *,
    call_tool: CallToolFn,
    list_tool_schemas: ListSchemasFn,
    max_rounds: int = 8,
) -> dict[str, Any]:
    """Gemini discovers and calls MCP tools (function calling), then returns a decision.

    Unlike decide_with_gemini(), the model itself chooses which MCP tools to invoke
    (read metrics/checkpoints, then apply_recovery_action).
    """
    from google import genai
    from google.genai import types

    api_key = os.environ["GEMINI_API_KEY"].strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    client = genai.Client(api_key=api_key)

    schemas = await list_tool_schemas()
    declarations: list[types.FunctionDeclaration] = []
    for item in schemas:
        name = item["name"]
        if name not in AGENT_MCP_TOOLS:
            continue
        declarations.append(
            types.FunctionDeclaration(
                name=name,
                description=item.get("description") or name,
                parameters_json_schema=_schema_for_gemini(item.get("input_schema")),
            )
        )
    if not declarations:
        raise RuntimeError("No MCP tools available for Gemini agent")

    prompt = """Eres el agente de tolerancia a fallas de TrainGuard (MNIST real + PyTorch).
Debes usar las tools MCP disponibles (function calling) para inspeccionar el run
y aplicar la recuperación. No inventes métricas: léelas con las tools.

Tools MCP que puedes llamar:
- get_training_status
- get_latest_metrics
- list_checkpoints
- apply_recovery_action

Reglas:
1) Primero lee estado/métricas/checkpoints con las tools MCP.
2) Decide UNA acción: alert_only | rollback_checkpoint | reduce_lr_and_resume | stop_training
3) Si confidence >= 0.75 y la acción no es alert_only → llama apply_recovery_action vía MCP.
4) Si solo alertas o confianza baja → llama apply_recovery_action con action=alert_only.
5) rollback_checkpoint carga pesos reales de best.pt (no reescribe el mejor resultado).
6) Cuando termines, responde SOLO JSON (sin markdown):
{
  "action": "...",
  "confidence": 0.0,
  "reason": "...",
  "evidence": ["..."],
  "applied": true
}

Heurísticas:
- val_loss NaN, weights_finite=false o fault=nan_loss → rollback_checkpoint (alta confianza)
- LR alto / fault=exploding_lr → reduce_lr_and_resume (rollback si unhealthy)
- stall → reduce_lr_and_resume
- sano → alert_only
"""

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=prompt)])
    ]
    tool_config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    applied = False
    last_apply_state: dict[str, Any] | None = None
    gemini_tool_calls: list[dict[str, Any]] = []
    final_text = ""

    for _ in range(max_rounds):
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=tool_config,
        )

        function_calls = list(response.function_calls or [])
        candidate = (response.candidates or [None])[0]
        model_content = candidate.content if candidate is not None else None

        if not function_calls:
            final_text = (response.text or "").strip()
            break

        if model_content is not None:
            contents.append(model_content)

        response_parts: list[types.Part] = []
        for fc in function_calls:
            name = fc.name or ""
            args = _args_to_dict(fc.args)
            gemini_tool_calls.append({"tool": name, "arguments": args})

            if name not in AGENT_MCP_TOOLS:
                payload: Any = {"error": f"Tool '{name}' not allowed for Gemini MCP agent"}
            else:
                try:
                    payload = await call_tool(name, args)
                    if name == "apply_recovery_action":
                        applied = True
                        if isinstance(payload, dict):
                            last_apply_state = payload
                except Exception as exc:  # noqa: BLE001 — feed error back to the model
                    payload = {"error": str(exc)}

            # Keep function responses compact for the model.
            if not isinstance(payload, dict):
                payload = {"result": payload}
            response_parts.append(
                types.Part.from_function_response(
                    name=name,
                    response={"result": payload},
                )
            )

        contents.append(types.Content(role="user", parts=response_parts))
    else:
        raise RuntimeError("Gemini MCP agent exceeded max tool rounds")

    if not final_text:
        # Model finished only with tool calls; synthesize from last apply.
        action = "alert_only"
        if last_apply_state and isinstance(last_apply_state.get("last_action"), dict):
            action = str(last_apply_state["last_action"].get("action") or "alert_only")
        elif gemini_tool_calls:
            for call in reversed(gemini_tool_calls):
                if call["tool"] == "apply_recovery_action":
                    action = str(call["arguments"].get("action") or "alert_only")
                    break
        final_text = json.dumps(
            {
                "action": action,
                "confidence": 0.85 if applied else 0.6,
                "reason": "Gemini completed via MCP tools without a final text summary.",
                "evidence": [f"MCP:{c['tool']}" for c in gemini_tool_calls],
                "applied": applied,
            }
        )

    try:
        parsed = _extract_json(final_text)
    except ValueError:
        parsed = {
            "action": "alert_only",
            "confidence": 0.5,
            "reason": final_text[:400] or "Gemini returned no JSON",
            "evidence": [f"MCP:{c['tool']}" for c in gemini_tool_calls],
            "applied": applied,
        }

    decision = _normalize_decision(
        parsed,
        model=model,
        decided_by="gemini_mcp",
    )
    decision["gemini_requested_mcp_tools"] = gemini_tool_calls
    decision["llm_uses_mcp"] = True

    if "applied" in parsed:
        applied = bool(parsed.get("applied")) or applied

    return {
        "decision": decision,
        "applied": applied,
        "state": last_apply_state,
        "gemini_mcp_rounds": len(gemini_tool_calls),
    }
