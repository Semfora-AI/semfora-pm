"""Shared Linear ticket operations for CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import get_client_for_path
from ..output.pagination import paginate


def _format_issue_summary(issue: dict) -> dict:
    """Format a Linear issue for list display."""
    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "state": issue.get("state", {}).get("name"),
        "priority": issue.get("priority"),
        "assignee": issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
        "labels": [label.get("name") for label in issue.get("labels", {}).get("nodes", [])],
        "url": issue.get("url"),
    }


def _filter_issues(
    issues: list[dict],
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    sprint_only: bool = False,
) -> list[dict]:
    filtered = issues

    if state:
        filtered = [i for i in filtered if i.get("state", {}).get("name") == state]
    if label:
        filtered = [
            i for i in filtered
            if any(l.get("name") == label for l in i.get("labels", {}).get("nodes", []))
        ]
    if priority is not None:
        filtered = [i for i in filtered if i.get("priority") == priority]
    if sprint_only:
        filtered = [
            i for i in filtered
            if i.get("state", {}).get("name") in {"Todo", "In Progress", "In Review"}
        ]

    return filtered


def list_tickets(
    path: Optional[Path] = None,
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    sprint_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    issues = client.get_team_issues(context.team_id, limit=max(limit * 2, 50))
    filtered = _filter_issues(issues, state=state, label=label, priority=priority, sprint_only=sprint_only)
    summaries = [_format_issue_summary(i) for i in filtered]
    page, pagination = paginate(summaries, limit, offset)

    return {
        "tickets": page,
        "pagination": pagination,
        "context": {
            "team_id": context.team_id,
            "team_name": context.team_name,
        },
    }


def get_ticket(identifier: str, path: Optional[Path] = None) -> dict:
    client, context = get_client_for_path(path)
    issue = client.get_issue_full(identifier)
    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    return {
        "context": {
            "team_id": context.team_id,
            "team_name": context.team_name,
        },
        "ticket": issue,
    }


def search_tickets(
    query: str,
    path: Optional[Path] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    issues = client.search_issues(query, context.team_id, limit=limit + offset)
    summaries = [_format_issue_summary(i) for i in issues]
    page, pagination = paginate(summaries, limit, offset)

    return {
        "query": query,
        "tickets": page,
        "pagination": pagination,
        "context": {
            "team_id": context.team_id,
            "team_name": context.team_name,
        },
    }


def update_ticket_status(
    identifier: str,
    state_name: str,
    path: Optional[Path] = None,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    issue = client.get_issue_by_identifier(identifier)
    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    states = client.get_team_states(context.team_id)
    state_id = next((s["id"] for s in states if s["name"] == state_name), None)
    if not state_id:
        return {"error": f"State not found: {state_name}"}

    result = client.update_issue(issue["id"], state_id=state_id)
    return {
        "ticket": result,
        "context": {
            "team_id": context.team_id,
            "team_name": context.team_name,
        },
    }
