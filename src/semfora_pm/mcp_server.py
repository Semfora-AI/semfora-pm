"""MCP Server for Semfora PM - Linear ticket management.

This MCP server exposes Linear ticket management capabilities to AI assistants,
enabling ticket-first development workflows.
"""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .linear_client import LinearClient, LinearConfig

# Create the MCP server
mcp = FastMCP(
    "semfora-pm",
    instructions="""Semfora PM - Linear Ticket Management

This server provides access to Linear tickets for the Semfora project.
Use these tools to:
- Check sprint status before starting work
- Get full ticket details including requirements and acceptance criteria
- Find related tickets (blocking, blocked by, related)
- Search for tickets by various criteria
- Update ticket status as work progresses

IMPORTANT: All development work should be associated with a ticket.
Before implementing any feature or fix, always verify the ticket exists
and review its full requirements."""
)


def _get_client() -> LinearClient:
    """Get configured Linear client."""
    config = LinearConfig.load()
    if not config:
        raise ValueError(
            "Linear not configured. Run 'semfora-pm auth setup' first or set LINEAR_API_KEY env var."
        )
    return LinearClient(config)


def _format_priority(priority: int) -> str:
    """Convert priority number to string."""
    return {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}.get(priority, str(priority))


def _format_issue_summary(issue: dict) -> dict:
    """Format issue for summary display."""
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
    return {
        "identifier": issue["identifier"],
        "title": issue["title"],
        "state": issue["state"]["name"],
        "priority": _format_priority(issue.get("priority", 0)),
        "estimate": issue.get("estimate"),
        "labels": labels,
        "url": issue.get("url"),
    }


@mcp.tool()
def sprint_status() -> dict:
    """Get current sprint status showing all active tickets.

    Returns tickets grouped by state: In Progress, In Review, and Todo.
    Use this FIRST before starting any work to see what's currently active.
    """
    client = _get_client()
    config = LinearConfig.load()

    if not config.team_id:
        return {"error": "No default team configured. Run 'semfora-pm auth setup' first."}

    issues = client.get_team_issues(config.team_id)

    # Group by state
    todo = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "Todo"]
    in_progress = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "In Progress"]
    in_review = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "In Review"]

    return {
        "in_progress": in_progress,
        "in_review": in_review,
        "todo": todo,
        "summary": {
            "in_progress_count": len(in_progress),
            "in_review_count": len(in_review),
            "todo_count": len(todo),
            "total_active": len(in_progress) + len(in_review) + len(todo),
        }
    }


@mcp.tool()
def get_ticket(identifier: str) -> dict:
    """Get full details for a specific ticket.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)

    Returns complete ticket information including:
    - Title, description, state, priority, estimate
    - Labels, assignee, project, cycle
    - Related tickets (blocks, blocked by, related)
    - Sub-issues and parent issue
    - Full description with requirements and acceptance criteria

    ALWAYS use this before implementing a ticket to get full requirements.
    """
    client = _get_client()
    issue = client.get_issue_full(identifier)

    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    # Format labels
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

    # Format assignee
    assignee = issue.get("assignee")
    assignee_str = assignee["name"] if assignee else None

    # Format project
    project = issue.get("project")
    project_str = project["name"] if project else None

    # Format cycle
    cycle = issue.get("cycle")
    cycle_str = cycle["name"] if cycle else None

    # Format parent issue
    parent = issue.get("parent")
    parent_info = None
    if parent:
        parent_info = {
            "identifier": parent["identifier"],
            "title": parent["title"],
        }

    # Format sub-issues
    sub_issues = issue.get("children", {}).get("nodes", [])
    sub_issues_list = [
        {"identifier": s["identifier"], "title": s["title"]}
        for s in sub_issues
    ]

    # Format relations
    relations = issue.get("relations", {}).get("nodes", [])

    def format_relations(rel_type: str) -> list:
        rels = [r for r in relations if r.get("type") == rel_type]
        return [
            {
                "identifier": r.get("relatedIssue", {}).get("identifier"),
                "title": r.get("relatedIssue", {}).get("title"),
            }
            for r in rels
        ]

    return {
        "identifier": issue["identifier"],
        "title": issue["title"],
        "state": issue["state"]["name"],
        "priority": _format_priority(issue.get("priority", 0)),
        "estimate": issue.get("estimate"),
        "assignee": assignee_str,
        "labels": labels,
        "project": project_str,
        "cycle": cycle_str,
        "parent": parent_info,
        "sub_issues": sub_issues_list,
        "blocks": format_relations("blocks"),
        "blocked_by": format_relations("blocked"),
        "related": format_relations("related"),
        "description": issue.get("description") or "No description",
        "url": issue.get("url"),
        "created_at": issue.get("createdAt", "")[:10] if issue.get("createdAt") else None,
        "updated_at": issue.get("updatedAt", "")[:10] if issue.get("updatedAt") else None,
    }


@mcp.tool()
def list_tickets(
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
) -> dict:
    """List tickets with optional filtering.

    Args:
        state: Filter by state (Backlog, Todo, In Progress, In Review, Done)
        label: Filter by label name
        priority: Filter by priority (1=Urgent, 2=High, 3=Medium, 4=Low)
        limit: Maximum tickets to return (default 20)

    Returns list of tickets matching criteria.
    """
    client = _get_client()
    config = LinearConfig.load()

    if not config.team_id:
        return {"error": "No default team configured."}

    issues = client.get_team_issues(config.team_id)

    # Apply filters
    if state:
        issues = [i for i in issues if i["state"]["name"].lower() == state.lower()]

    if label:
        issues = [
            i for i in issues
            if any(l["name"].lower() == label.lower() for l in i.get("labels", {}).get("nodes", []))
        ]

    if priority is not None:
        issues = [i for i in issues if i.get("priority") == priority]

    # Sort by priority then by identifier
    issues = sorted(issues, key=lambda i: (i.get("priority", 4), i["identifier"]))

    # Limit results
    issues = issues[:limit]

    return {
        "tickets": [_format_issue_summary(i) for i in issues],
        "count": len(issues),
    }


@mcp.tool()
def sprint_suggest(points: int = 20, label: Optional[str] = None) -> dict:
    """Suggest tickets for next sprint based on priority and points budget.

    Args:
        points: Target story points for sprint (default 20)
        label: Optional label to filter by (e.g., 'phase-2.5')

    Returns suggested tickets that fit the point budget, sorted by priority.
    """
    client = _get_client()
    config = LinearConfig.load()

    if not config.team_id:
        return {"error": "No default team configured."}

    issues = client.get_team_issues(config.team_id)

    # Filter to backlog only
    backlog = [i for i in issues if i["state"]["name"] == "Backlog"]

    if label:
        backlog = [
            i for i in backlog
            if any(l["name"].lower() == label.lower() for l in i.get("labels", {}).get("nodes", []))
        ]

    if not backlog:
        return {"error": "No backlog tickets found", "suggested": [], "total_points": 0}

    # Sort by priority (lower is higher priority)
    sorted_issues = sorted(backlog, key=lambda i: (i.get("priority", 4), -(i.get("estimate") or 0)))

    # Greedily select tickets
    suggested = []
    current_points = 0

    for issue in sorted_issues:
        if current_points >= points:
            break
        estimate = issue.get("estimate") or 2  # Default estimate
        if current_points + estimate <= points:
            suggested.append(_format_issue_summary(issue))
            current_points += estimate

    # Get next up (over budget)
    next_up = [
        _format_issue_summary(i) for i in sorted_issues
        if _format_issue_summary(i) not in suggested
    ][:5]

    return {
        "suggested": suggested,
        "total_points": current_points,
        "target_points": points,
        "next_up": next_up,
    }


@mcp.tool()
def search_tickets(query: str, limit: int = 10) -> dict:
    """Search for tickets by text query.

    Args:
        query: Search text to match against title and description
        limit: Maximum results to return (default 10)

    Returns matching tickets.
    """
    client = _get_client()

    results = client.search_issues(query)

    if not results:
        return {"tickets": [], "count": 0}

    tickets = [_format_issue_summary(i) for i in results[:limit]]

    return {
        "tickets": tickets,
        "count": len(tickets),
    }


@mcp.tool()
def update_ticket_status(identifier: str, state: str) -> dict:
    """Update a ticket's status.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)
        state: New state (Backlog, Todo, In Progress, In Review, Done, Canceled)

    Use this to move tickets through the workflow as you work on them.
    """
    client = _get_client()

    # Get issue to find team
    issue = client.get_issue_by_identifier(identifier)
    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    team_id = issue.get("team", {}).get("id")
    if not team_id:
        return {"error": "Could not determine team for ticket"}

    # Get state ID
    states = client.get_team_states(team_id)
    state_id = None
    for s in states:
        if s["name"].lower() == state.lower():
            state_id = s["id"]
            break

    if not state_id:
        available = [s["name"] for s in states]
        return {"error": f"Invalid state '{state}'. Available: {available}"}

    # Update the issue
    result = client.update_issue(issue["id"], {"stateId": state_id})

    return {
        "success": True,
        "identifier": identifier,
        "new_state": state,
        "url": result.get("url"),
    }


@mcp.tool()
def get_related_tickets(identifier: str) -> dict:
    """Get all tickets related to a specific ticket.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)

    Returns tickets that:
    - Block this ticket
    - Are blocked by this ticket
    - Are related to this ticket
    - Are sub-issues of this ticket
    - Are the parent of this ticket

    Use this to understand the full context and dependencies before working on a ticket.
    """
    client = _get_client()
    issue = client.get_issue_full(identifier)

    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    # Get relations
    relations = issue.get("relations", {}).get("nodes", [])

    def get_relation_details(rel_type: str) -> list:
        rels = [r for r in relations if r.get("type") == rel_type]
        result = []
        for r in rels:
            related = r.get("relatedIssue", {})
            if related:
                result.append({
                    "identifier": related.get("identifier"),
                    "title": related.get("title"),
                    "state": related.get("state", {}).get("name"),
                    "url": related.get("url"),
                })
        return result

    # Get parent
    parent = issue.get("parent")
    parent_info = None
    if parent:
        parent_info = {
            "identifier": parent["identifier"],
            "title": parent["title"],
            "state": parent.get("state", {}).get("name"),
        }

    # Get sub-issues
    sub_issues = issue.get("children", {}).get("nodes", [])
    sub_list = [
        {
            "identifier": s["identifier"],
            "title": s["title"],
            "state": s.get("state", {}).get("name"),
        }
        for s in sub_issues
    ]

    return {
        "identifier": identifier,
        "title": issue["title"],
        "blocks": get_relation_details("blocks"),
        "blocked_by": get_relation_details("blocked"),
        "related": get_relation_details("related"),
        "parent": parent_info,
        "sub_issues": sub_list,
    }


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
