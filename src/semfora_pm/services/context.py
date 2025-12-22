"""Context and client resolution helpers shared by CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..linear_client import LinearClient, LinearConfig, AuthenticationError
from ..pm_config import PMContext, resolve_context, scan_pm_directories, get_context_help_message


def resolve_context_info(path: Optional[Path] = None) -> dict:
    """Return context info and help text if not configured."""
    context = resolve_context(path)
    return {
        "config_source": context.config_source,
        "config_path": str(context.config_path) if context.config_path else None,
        "provider": context.provider,
        "team_id": context.team_id,
        "team_name": context.team_name,
        "project_id": context.project_id,
        "project_name": context.project_name,
        "api_key_configured": context.api_key is not None,
        "api_key_env": context.api_key_env,
        "help": get_context_help_message(context) if context.config_source == "none" else None,
    }


def get_client_for_path(path: Optional[Path] = None) -> tuple[LinearClient, PMContext]:
    """Return Linear client + resolved context for a path."""
    if path:
        return LinearClient.from_context(path), resolve_context(path)

    context = resolve_context()
    if context.api_key and context.has_team():
        return LinearClient.from_context(), context

    config = LinearConfig.load()
    if not config:
        raise AuthenticationError("Linear API key not configured.")

    return LinearClient(config), context


def scan_contexts(path: Optional[Path] = None, max_depth: int = 3) -> list[dict]:
    """Scan for .pm configs and return summarized info."""
    dirs = scan_pm_directories(Path(path) if path else None, max_depth)
    return [
        {
            "path": str(d.path),
            "config_path": str(d.config_path),
            "provider": d.provider,
            "team_id": d.team_id,
            "team_name": d.team_name,
            "project_id": d.project_id,
            "project_name": d.project_name,
        }
        for d in dirs
    ]
