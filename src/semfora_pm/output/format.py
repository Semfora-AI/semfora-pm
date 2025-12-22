"""Output formatting utilities for CLI and MCP."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional


def _encode_toon(payload: Any) -> str:
    """Encode payload to TOON format when available, else JSON."""
    try:
        from toon_format import encode  # type: ignore
    except Exception:
        return json.dumps(payload, separators=(",", ":"))
    return encode(payload)


def format_response(
    payload: Any,
    output_format: str = "toon",
    text_renderer: Optional[Callable[[Any], str]] = None,
) -> dict:
    """Normalize response with format metadata and content.

    Args:
        payload: Data to serialize.
        output_format: "toon", "json", or "text".
        text_renderer: Optional renderer for text output.
    """
    output_format = (output_format or "toon").lower()

    if output_format == "json":
        return {"format": "json", "content": payload}
    if output_format == "text":
        content = text_renderer(payload) if text_renderer else json.dumps(payload, indent=2)
        return {"format": "text", "content": content}

    return {"format": "toon", "content": _encode_toon(payload)}


def render_cli(response: dict) -> str:
    """Render a formatted response into a CLI string."""
    fmt = response.get("format")
    content = response.get("content")
    if fmt == "json":
        return json.dumps(content, indent=2)
    if fmt == "text":
        return str(content)
    return str(content)
