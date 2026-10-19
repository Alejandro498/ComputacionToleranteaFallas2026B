"""Gemini decides recovery action; TrainGuard applies it via MCP tools."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

ALLOWED_ACTIONS = {
    "alert_only",
    "rollback_checkpoint",
    "reduce_lr_and_resume",
    "stop_training",
}


def gemini_enabled() -> bool:
    if os.getenv("USE_GEMINI", "true").lower() in {"0", "false", "no"}:
        return False
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


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


def decide_with_gemini(context: dict[str, Any]) -> dict[str, Any]:
    """Ask Gemini for a recovery decision given MCP-fetched training context."""
    from google import genai

    api_key = os.environ["GEMINI_API_KEY"].strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    client = genai.Client(api_key=api_key)

    prompt = f"""Eres el agente de tolerancia a fallas de TrainGuard (MLOps).
Analiza el contexto del entrenamiento y decide UNA acción.

Acciones permitidas:
- alert_only
- rollback_checkpoint
- reduce_lr_and_resume
- stop_training

Reglas:
- Si loss es NaN o fault=nan_loss → rollback_checkpoint (alta confianza).
- Si LR muy alto o fault=exploding_lr → reduce_lr_and_resume.
- Si stall leve → alert_only o reduce_lr_and_resume con confianza media.
- Si todo sano → alert_only.
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
        "decided_by": "gemini",
        "model": model,
    }
