"""Shared output formatting for CLI and MCP."""

from .format import format_response, render_cli
from .pagination import build_pagination, paginate

__all__ = ["format_response", "render_cli", "build_pagination", "paginate"]
