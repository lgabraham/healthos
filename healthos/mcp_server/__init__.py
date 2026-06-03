"""HealthOS MCP server package.

Run as a standalone process: ``python -m healthos.mcp_server``.
"""

from .server import mcp

__all__ = ["mcp"]
