"""TrainGuard MCP server for Claude Desktop and the n8n HTTP bridge."""

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
        "TrainGuard monitors a real image-training run (PyTorch TinyCNN) on "
        "MNIST, Fashion-MNIST, CIFAR-10 or a custom ImageFolder. It detects "
        "faults, rolls back to .pt checkpoints, and checks that the best "
        "result is preserved."
    ),
)


@mcp.tool
def list_datasets() -> dict:
    """List built-in datasets and custom folders under data/custom/."""
    return engine.available_datasets()


@mcp.tool
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
) -> dict:
    """Start a training run. dataset: auto | mnist | fashion_mnist | cifar10 | custom."""
    return engine.start_training(
        max_epochs=max_epochs,
        lr=lr,
        train_size=train_size,
        val_size=val_size,
        batch_size=batch_size,
        seed=seed,
        dataset=dataset,
        dataset_path=dataset_path,
        dataset_url=dataset_url,
        image_size=image_size,
    )


@mcp.tool
def advance_epochs(n: int = 1) -> dict:
    """Train N real epochs and persist .pt checkpoints."""
    return engine.advance_epochs(n=n)


@mcp.tool
def get_training_status() -> dict:
    """Get full status of the current training run."""
    return engine.get_status()


@mcp.tool
def get_latest_metrics(limit: int = 5) -> dict:
    """Get the latest training metrics (val loss/acc)."""
    return engine.get_latest_metrics(limit=limit)


@mcp.tool
def list_checkpoints() -> dict:
    """List saved .pt checkpoints, hashes, and the current best."""
    return engine.list_checkpoints()


@mcp.tool
def inject_fault(kind: str = "nan_loss") -> dict:
    """Arm a real fault: nan_loss | exploding_lr | stall. Does not train."""
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


@mcp.tool
def compare_recovery() -> dict:
    """Compare best.pt before the fault vs after recovery (preserved_best, resumed)."""
    return engine.compare_recovery()


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
