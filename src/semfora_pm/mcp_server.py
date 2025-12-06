"""MCP Server for Semfora PM - Linear ticket management.

This MCP server exposes Linear ticket management capabilities to AI assistants,
enabling ticket-first development workflows.

Supports directory-based configuration via .pm/config.yaml files.
"""

from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .linear_client import AuthenticationError, LinearClient, LinearConfig
from .pm_config import (
    PMContext,
    PMDirectoryInfo,
    resolve_context,
    scan_pm_directories,
    get_context_help_message,
)

# Create the MCP server
mcp = FastMCP(
    "semfora-pm",
    instructions="""Semfora PM - Linear Ticket Management

This server provides access to Linear tickets for project management.

DIRECTORY-BASED CONFIGURATION:
- Uses .pm/config.yaml to configure team/project per directory
- Automatically detects config from current directory or parents
- Falls back to user config (~/.config/semfora-pm/config.json)
- Use scan_pm_dirs to discover all configured directories

MULTI-REPO SUPPORT:
- Each tool accepts --path to target a specific directory
- Use detect_pm_context to see which team/project is configured
- Different directories can use different Linear teams/projects

WORKFLOW:
1. Use scan_pm_dirs to discover configured directories
2. Use detect_pm_context to verify team/project for a path
3. Use sprint_status to check active tickets
4. Use get_ticket to get full requirements before implementing
5. Use update_ticket_status as you work

IMPORTANT: All development work should be associated with a ticket.
Before implementing any feature or fix, always verify the ticket exists
and review its full requirements."""
)


def _get_client_for_path(path: Optional[str] = None) -> tuple[LinearClient, PMContext]:
    """Get configured Linear client for a path.

    Returns (client, context) tuple.
    Raises AuthenticationError if not configured.
    """
    path_obj = Path(path) if path else None
    context = resolve_context(path_obj)

    if not context.api_key:
        raise AuthenticationError(
            "Linear authentication not configured.",
            suggestions=[
                "Set: export LINEAR_API_KEY=lin_api_xxx",
                "Or run: semfora-pm auth setup",
            ],
        )

    if not context.has_team():
        raise ValueError(
            "No team configured. Create .pm/config.yaml or run 'semfora-pm auth setup'."
        )

    client = LinearClient.from_context(context)
    return client, context


def _get_client_safe(path: Optional[str] = None) -> tuple[Optional[LinearClient], Optional[PMContext], Optional[dict]]:
    """Get client with proper error handling."""
    try:
        client, context = _get_client_for_path(path)
        return client, context, None
    except AuthenticationError as e:
        return None, None, {
            "error": "authentication_required",
            "message": str(e),
            "suggestions": e.suggestions,
            "help": LinearConfig.get_auth_help_message(),
        }
    except ValueError as e:
        return None, None, {
            "error": "configuration_required",
            "message": str(e),
        }


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
def scan_pm_dirs(
    path: Optional[str] = None,
    max_depth: int = 3,
) -> dict:
    """Scan directory for all .pm/ configurations.

    Args:
        path: Base directory to scan (defaults to current directory)
        max_depth: Maximum directory depth to search (default 3)

    Returns list of directories with PM configuration including:
    - path: Directory path
    - provider: PM provider (linear)
    - team_id/team_name: Configured team
    - project_id/project_name: Configured project

    Use this to discover which directories have PM configuration.
    """
    base_path = Path(path) if path else None
    dirs = scan_pm_directories(base_path, max_depth)

    formatted = []
    for d in dirs:
        formatted.append({
            "path": str(d.path),
            "config_path": str(d.config_path),
            "provider": d.provider,
            "team_id": d.team_id,
            "team_name": d.team_name,
            "project_id": d.project_id,
            "project_name": d.project_name,
        })

    return {
        "directories": formatted,
        "count": len(formatted),
        "base_path": str(base_path or Path.cwd()),
    }


@mcp.tool()
def detect_pm_context(path: Optional[str] = None) -> dict:
    """Detect PM context for a path.

    Args:
        path: Directory to check (defaults to current directory)

    Returns resolved PM configuration including:
    - config_source: Where config was found (directory, parent, user, none)
    - config_path: Path to config file
    - provider: PM provider
    - team_id/team_name: Resolved team
    - project_id/project_name: Resolved project
    - api_key configured: Whether auth is set up

    Use this to verify which team/project will be used for a directory.
    """
    path_obj = Path(path) if path else None
    context = resolve_context(path_obj)

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


@mcp.tool()
def check_auth(path: Optional[str] = None) -> dict:
    """Check authentication status for a path.

    Args:
        path: Directory to check context for (defaults to current directory)

    Returns authentication status and configuration info.
    """
    path_obj = Path(path) if path else None
    context = resolve_context(path_obj)

    if not context.api_key:
        return {
            "authenticated": False,
            "help": LinearConfig.get_auth_help_message(),
        }

    # Verify API key works
    try:
        config = LinearConfig(api_key=context.api_key)
        client = LinearClient(config)
        teams = client.get_teams()

        return {
            "authenticated": True,
            "config_source": context.config_source,
            "config_path": str(context.config_path) if context.config_path else None,
            "team_id": context.team_id,
            "team_name": context.team_name,
            "available_teams": [{"id": t["id"], "name": t["name"]} for t in teams],
        }
    except Exception as e:
        return {
            "authenticated": False,
            "error": str(e),
            "help": LinearConfig.get_auth_help_message(),
        }


@mcp.tool()
def sprint_status(path: Optional[str] = None, aggregate: bool = False) -> dict:
    """Get current sprint status showing all active tickets.

    Args:
        path: Directory to get context from (defaults to current directory)
        aggregate: If True, scan for all .pm/ configs and aggregate tickets across
                  all configured teams/projects, deduping when they share the same project.
                  Useful when calling from a base directory containing multiple repos.

    Returns tickets grouped by state: In Progress, In Review, and Todo.
    Use this FIRST before starting any work to see what's currently active.
    """
    if aggregate:
        return _sprint_status_aggregated(path)

    client, context, error = _get_client_safe(path)
    if error:
        return error

    if not client.config.team_id:
        return {"error": "No team configured. Create .pm/config.yaml or run 'semfora-pm auth setup'."}

    issues = client.get_team_issues(client.config.team_id)

    # Group by state
    todo = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "Todo"]
    in_progress = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "In Progress"]
    in_review = [_format_issue_summary(i) for i in issues if i["state"]["name"] == "In Review"]

    return {
        "context": {
            "config_source": context.config_source,
            "team_id": context.team_id,
            "team_name": context.team_name,
        },
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


def _sprint_status_aggregated(base_path: Optional[str] = None) -> dict:
    """Aggregate sprint status across all .pm/ configs found in directory tree.

    Handles deduplication when multiple configs point to the same team/project.
    """
    path_obj = Path(base_path) if base_path else Path.cwd()
    dirs = scan_pm_directories(path_obj, max_depth=3)

    if not dirs:
        # Fall back to single context (might be inherited from parent)
        context = resolve_context(path_obj)
        if context.has_team():
            return sprint_status(base_path, aggregate=False)
        return {"error": "No .pm/ configurations found. Run 'semfora-pm init' to create one."}

    # Track unique team+project combinations to avoid duplicate API calls
    seen_configs: set[tuple] = set()  # (team_id, team_name, project_id, project_name)
    all_issues: dict[str, dict] = {}  # identifier -> issue (for deduping)
    projects_fetched: list[dict] = []  # Track which projects we fetched from
    errors: list[dict] = []

    for dir_info in dirs:
        # Create a config key for deduplication
        config_key = (
            dir_info.team_id,
            dir_info.team_name,
            dir_info.project_id,
            dir_info.project_name,
        )

        if config_key in seen_configs:
            continue
        seen_configs.add(config_key)

        # Try to get client for this directory
        try:
            client, context = _get_client_for_path(str(dir_info.path))
        except (AuthenticationError, ValueError) as e:
            errors.append({
                "path": str(dir_info.path),
                "error": str(e),
            })
            continue

        if not client.config.team_id:
            continue

        # Fetch issues
        try:
            issues = client.get_team_issues(client.config.team_id)

            project_info = {
                "path": str(dir_info.path),
                "team_id": client.config.team_id,
                "team_name": context.team_name,
                "project_name": context.project_name,
                "issue_count": len(issues),
            }
            projects_fetched.append(project_info)

            # Add issues, deduping by identifier
            for issue in issues:
                identifier = issue["identifier"]
                if identifier not in all_issues:
                    all_issues[identifier] = issue
        except Exception as e:
            errors.append({
                "path": str(dir_info.path),
                "error": str(e),
            })

    if not all_issues:
        return {
            "error": "No tickets found across configured projects",
            "projects_checked": projects_fetched,
            "errors": errors if errors else None,
        }

    # Group by state
    issues_list = list(all_issues.values())
    todo = [_format_issue_summary(i) for i in issues_list if i["state"]["name"] == "Todo"]
    in_progress = [_format_issue_summary(i) for i in issues_list if i["state"]["name"] == "In Progress"]
    in_review = [_format_issue_summary(i) for i in issues_list if i["state"]["name"] == "In Review"]

    return {
        "aggregated": True,
        "projects": projects_fetched,
        "in_progress": in_progress,
        "in_review": in_review,
        "todo": todo,
        "summary": {
            "in_progress_count": len(in_progress),
            "in_review_count": len(in_review),
            "todo_count": len(todo),
            "total_active": len(in_progress) + len(in_review) + len(todo),
            "projects_count": len(projects_fetched),
            "unique_tickets": len(all_issues),
        },
        "errors": errors if errors else None,
    }


@mcp.tool()
def get_ticket(identifier: str, path: Optional[str] = None) -> dict:
    """Get full details for a specific ticket.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)
        path: Directory to get context from (defaults to current directory)

    Returns complete ticket information including:
    - Title, description, state, priority, estimate
    - Labels, assignee, project, cycle
    - Related tickets (blocks, blocked by, related)
    - Sub-issues and parent issue
    - Full description with requirements and acceptance criteria

    ALWAYS use this before implementing a ticket to get full requirements.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

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
def get_ticket_summary(identifier: str, path: Optional[str] = None) -> dict:
    """Get minimal ticket info for CLI status bar display.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)
        path: Directory to get context from (defaults to current directory)

    Returns minimal ticket information optimized for display (<100 tokens):
    - identifier: Ticket ID
    - title: Title (truncated to 50 chars if needed)
    - state: Current state
    - priority: Priority level
    - assignee: Assignee name (optional)

    Use this for CLI footer/status bar display where space is limited.
    For full ticket details, use get_ticket instead.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

    issue = client.get_issue_by_identifier(identifier)

    if not issue:
        return {"error": "not_found", "message": f"Ticket {identifier} not found"}

    # Truncate title if too long for display
    title = issue.get("title", "")
    if len(title) > 50:
        title = title[:47] + "..."

    # Get assignee name
    assignee = issue.get("assignee")
    assignee_name = assignee.get("name") if assignee else None

    # Return minimal response (<100 tokens for CLI efficiency)
    return {
        "identifier": issue["identifier"],
        "title": title,
        "state": issue["state"]["name"],
        "priority": _format_priority(issue.get("priority", 0)),
        "assignee": assignee_name,
    }


@mcp.tool()
def list_tickets(
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
    path: Optional[str] = None,
    aggregate: bool = False,
) -> dict:
    """List tickets with optional filtering.

    Args:
        state: Filter by state (Backlog, Todo, In Progress, In Review, Done)
        label: Filter by label name
        priority: Filter by priority (1=Urgent, 2=High, 3=Medium, 4=Low)
        limit: Maximum tickets to return (default 20)
        path: Directory to get context from (defaults to current directory)
        aggregate: If True, scan for all .pm/ configs and aggregate tickets across
                  all configured teams/projects, deduping when they share the same project.

    Returns list of tickets matching criteria.
    """
    if aggregate:
        return _list_tickets_aggregated(state, label, priority, limit, path)

    client, context, error = _get_client_safe(path)
    if error:
        return error

    if not client.config.team_id:
        return {"error": "No team configured."}

    issues = client.get_team_issues(client.config.team_id)

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


def _list_tickets_aggregated(
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
    base_path: Optional[str] = None,
) -> dict:
    """Aggregate tickets across all .pm/ configs found in directory tree."""
    path_obj = Path(base_path) if base_path else Path.cwd()
    dirs = scan_pm_directories(path_obj, max_depth=3)

    if not dirs:
        # Fall back to single context
        context = resolve_context(path_obj)
        if context.has_team():
            return list_tickets(state, label, priority, limit, base_path, aggregate=False)
        return {"error": "No .pm/ configurations found."}

    # Track unique configs and aggregate issues
    seen_configs: set[tuple] = set()
    all_issues: dict[str, dict] = {}
    projects_fetched: list[dict] = []

    for dir_info in dirs:
        config_key = (dir_info.team_id, dir_info.team_name, dir_info.project_id, dir_info.project_name)
        if config_key in seen_configs:
            continue
        seen_configs.add(config_key)

        try:
            client, context = _get_client_for_path(str(dir_info.path))
            if not client.config.team_id:
                continue

            issues = client.get_team_issues(client.config.team_id)
            projects_fetched.append({
                "path": str(dir_info.path),
                "team_name": context.team_name,
                "project_name": context.project_name,
            })

            for issue in issues:
                if issue["identifier"] not in all_issues:
                    all_issues[issue["identifier"]] = issue
        except Exception:
            continue

    issues_list = list(all_issues.values())

    # Apply filters
    if state:
        issues_list = [i for i in issues_list if i["state"]["name"].lower() == state.lower()]

    if label:
        issues_list = [
            i for i in issues_list
            if any(l["name"].lower() == label.lower() for l in i.get("labels", {}).get("nodes", []))
        ]

    if priority is not None:
        issues_list = [i for i in issues_list if i.get("priority") == priority]

    # Sort and limit
    issues_list = sorted(issues_list, key=lambda i: (i.get("priority", 4), i["identifier"]))
    issues_list = issues_list[:limit]

    return {
        "aggregated": True,
        "projects": projects_fetched,
        "tickets": [_format_issue_summary(i) for i in issues_list],
        "count": len(issues_list),
    }


@mcp.tool()
def sprint_suggest(
    points: int = 20,
    label: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    """Suggest tickets for next sprint based on priority and points budget.

    Args:
        points: Target story points for sprint (default 20)
        label: Optional label to filter by (e.g., 'phase-2.5')
        path: Directory to get context from (defaults to current directory)

    Returns suggested tickets that fit the point budget, sorted by priority.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

    if not client.config.team_id:
        return {"error": "No team configured."}

    issues = client.get_team_issues(client.config.team_id)

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
def search_tickets(
    query: str,
    limit: int = 10,
    path: Optional[str] = None,
) -> dict:
    """Search for tickets by text query.

    Args:
        query: Search text to match against title and description
        limit: Maximum results to return (default 10)
        path: Directory to get context from (defaults to current directory)

    Returns matching tickets.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

    results = client.search_issues(query)

    if not results:
        return {"tickets": [], "count": 0}

    tickets = [_format_issue_summary(i) for i in results[:limit]]

    return {
        "tickets": tickets,
        "count": len(tickets),
    }


@mcp.tool()
def update_ticket_status(
    identifier: str,
    state: str,
    path: Optional[str] = None,
) -> dict:
    """Update a ticket's status.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)
        state: New state (Backlog, Todo, In Progress, In Review, Done, Canceled)
        path: Directory to get context from (defaults to current directory)

    Use this to move tickets through the workflow as you work on them.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

    # Get issue to find team
    issue = client.get_issue_by_identifier(identifier)
    if not issue:
        return {"error": f"Ticket not found: {identifier}"}

    # Use configured team_id or try to get from issue
    team_id = client.config.team_id
    if not team_id:
        return {"error": "No team configured"}

    # Get state ID
    states = client.get_team_states(team_id)
    state_id = states.get(state)

    if not state_id:
        available = list(states.keys())
        return {"error": f"Invalid state '{state}'. Available: {available}"}

    # Update the issue
    result = client.update_issue(issue["id"], state_id=state_id)

    return {
        "success": True,
        "identifier": identifier,
        "new_state": state,
        "url": result.get("url"),
    }


@mcp.tool()
def get_related_tickets(
    identifier: str,
    path: Optional[str] = None,
) -> dict:
    """Get all tickets related to a specific ticket.

    Args:
        identifier: Linear ticket identifier (e.g., SEM-45)
        path: Directory to get context from (defaults to current directory)

    Returns tickets that:
    - Block this ticket
    - Are blocked by this ticket
    - Are related to this ticket
    - Are sub-issues of this ticket
    - Are the parent of this ticket

    Use this to understand the full context and dependencies before working on a ticket.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return error

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
