"""Claude Desktop entrypoint for TrainGuard MCP (stdio, no banner)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainguard.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
