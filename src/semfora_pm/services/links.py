"""Shared issue relationship operations for CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import get_client_for_path


def link_blocks(blocker: str, blocked: str, path: Optional[Path] = None) -> dict:
    client, _ = get_client_for_path(path)
    blocker_id = client.get_issue_id_by_identifier(blocker)
    blocked_id = client.get_issue_id_by_identifier(blocked)

    if not blocker_id:
        return {"error": f"Could not find issue '{blocker}'"}
    if not blocked_id:
        return {"error": f"Could not find issue '{blocked}'"}

    client.create_issue_relation(blocker_id, blocked_id, "blocks")
    return {"blocker": blocker, "blocked": blocked, "relation": "blocks"}


def link_related(issue1: str, issue2: str, path: Optional[Path] = None) -> dict:
    client, _ = get_client_for_path(path)
    id1 = client.get_issue_id_by_identifier(issue1)
    id2 = client.get_issue_id_by_identifier(issue2)

    if not id1:
        return {"error": f"Could not find issue '{issue1}'"}
    if not id2:
        return {"error": f"Could not find issue '{issue2}'"}

    client.create_issue_relation(id1, id2, "related")
    return {"issue1": issue1, "issue2": issue2, "relation": "related"}
