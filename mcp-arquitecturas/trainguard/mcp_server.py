"""TrainGuard MCP server for Claude Desktop."""

from __future__ import annotations

import sys
from pathlib import Path

# Claude Desktop often ignores cwd; keep imports working anyway.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastmcp import FastMCP

from trainguard import engine

mcp = FastMCP(
    name="trainguard",
    instructions=(
        "TrainGuard monitors a toy neural-network training run, detects faults "
        "(NaN loss, exploding LR, stall), and applies recovery actions for fault tolerance."
    ),
)


@mcp.tool
def start_training(max_epochs: int = 12, lr: float = 0.01) -> dict:
    """Start a new toy training run."""
    return engine.start_training(max_epochs=max_epochs, lr=lr)


@mcp.tool
def advance_epochs(n: int = 1) -> dict:
    """Simulate N training epochs and append metrics."""
    return engine.advance_epochs(n=n)


@mcp.tool
def get_training_status() -> dict:
    """Get full status of the current training run."""
    return engine.get_status()


@mcp.tool
def get_latest_metrics(limit: int = 5) -> dict:
    """Get the latest training metrics."""
    return engine.get_latest_metrics(limit=limit)


@mcp.tool
def list_checkpoints() -> dict:
    """List saved checkpoints and best loss."""
    return engine.list_checkpoints()


@mcp.tool
def inject_fault(kind: str = "nan_loss") -> dict:
    """Inject a fault: nan_loss | exploding_lr | stall."""
    return engine.inject_fault(kind=kind)


@mcp.tool
def analyze_training() -> dict:
    """Analyze metrics and recommend a recovery action (JSON decision)."""
    return engine.analyze_and_recommend()


@mcp.tool
def apply_recovery_action(action: str, reason: str = "") -> dict:
    """Apply a recovery action: alert_only | rollback_checkpoint | reduce_lr_and_resume | stop_training."""
    return engine.apply_action(action=action, reason=reason)


@mcp.tool
def analyze_and_apply_recovery() -> dict:
    """Analyze metrics and automatically apply recovery when confidence is high."""
    return engine.analyze_and_apply()


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
