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
from .db import Database
from .local_tickets import LocalTicketManager, LocalTicket
from .dependencies import DependencyManager
from .external_items import (
    ExternalItemsManager,
    normalize_linear_status,
    normalize_linear_priority,
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


# ============================================================================
# Local Plans Helper Functions
# ============================================================================


def _get_db_for_path(path: Optional[str] = None) -> tuple[Database, str, PMContext]:
    """Get Database and project_id for a path.

    Returns (db, project_id, context) tuple.
    Creates project record if needed.
    """
    path_obj = Path(path) if path else None
    context = resolve_context(path_obj)

    db = Database(context.get_db_path())
    project_id = _ensure_project(db, context)

    return db, project_id, context


def _ensure_project(db: Database, context: PMContext) -> str:
    """Create or get project record for this context.

    Returns project_id.
    """
    import uuid

    if not context.config_path:
        # Use a default project for unconfigured contexts
        config_path = str(context.get_db_path().parent / "default")
    else:
        config_path = str(context.config_path)

    with db.connection() as conn:
        # Check if project exists
        row = conn.execute(
            "SELECT id FROM projects WHERE config_path = ?",
            (config_path,),
        ).fetchone()

        if row:
            return row["id"]

    # Create new project
    project_id = str(uuid.uuid4())
    name = context.project_name or context.team_name or "Default Project"

    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, config_path, provider, provider_team_id, provider_project_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                name,
                config_path,
                context.provider,
                context.team_id,
                context.project_id,
            ),
        )

    return project_id


def _cache_external_item(
    db: Database,
    project_id: str,
    provider_id: str,
    path: Optional[str] = None,
) -> Optional[str]:
    """Cache a Linear ticket and return its internal UUID.

    Fetches from Linear API if not cached or stale.
    Returns None if ticket not found.
    """
    manager = ExternalItemsManager(db, project_id)

    # Check if already cached and fresh
    existing = manager.get_by_provider_id(provider_id)
    if existing and not manager.is_stale(provider_id):
        return existing.id

    # Fetch from Linear
    client, context, error = _get_client_safe(path)
    if error or not client:
        # Can't fetch, return existing if available
        return existing.id if existing else None

    issue = client.get_issue_full(provider_id)
    if not issue:
        return existing.id if existing else None

    # Get epic info if available
    parent = issue.get("parent")
    epic_id = None
    epic_name = None
    if parent:
        epic_id = parent.get("identifier")
        epic_name = parent.get("title")

    # Get assignee info
    assignee = issue.get("assignee")
    assignee_id = assignee.get("id") if assignee else None
    assignee_name = assignee.get("name") if assignee else None

    # Get labels
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

    # Get cycle/sprint info
    cycle = issue.get("cycle")
    sprint_id = cycle.get("id") if cycle else None
    sprint_name = cycle.get("name") if cycle else None

    # Cache the item
    item = manager.cache_item(
        provider_id=provider_id,
        title=issue["title"],
        item_type="ticket",
        description=issue.get("description"),
        status=issue["state"]["name"],
        status_category=normalize_linear_status(issue["state"]["name"]),
        priority=normalize_linear_priority(issue.get("priority")),
        assignee=assignee_id,
        assignee_name=assignee_name,
        labels=labels,
        epic_id=epic_id,
        epic_name=epic_name,
        sprint_id=sprint_id,
        sprint_name=sprint_name,
        url=issue.get("url"),
        provider_data=issue,
        created_at_provider=issue.get("createdAt"),
        updated_at_provider=issue.get("updatedAt"),
    )

    return item.id


def _format_local_ticket(ticket: LocalTicket) -> dict:
    """Format a LocalTicket for API response (full details)."""
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "tags": ticket.tags,
        "parent_ticket": {
            "id": ticket.linked_ticket_id,
            "title": ticket.linked_ticket_title,
        } if ticket.linked_ticket_id else None,
        "epic": {
            "id": ticket.linked_epic_id,
            "name": ticket.linked_epic_name,
        } if ticket.linked_epic_id else None,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "completed_at": ticket.completed_at,
    }


def _format_local_ticket_summary(ticket: LocalTicket) -> dict:
    """Format a LocalTicket for list display (minimal, ~25 tokens vs ~100+).

    Excludes description, timestamps, and nested objects to minimize token usage.
    Use local_ticket_get() to fetch full details for a specific ticket.
    """
    return {
        "id": ticket.id[:8],  # Short ID for display
        "full_id": ticket.id,  # Full ID for lookups
        "title": ticket.title[:80] + "..." if len(ticket.title) > 80 else ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "tags": ticket.tags[:3] if ticket.tags else [],  # Max 3 tags
        "parent_ticket": ticket.linked_ticket_id,  # Just the ID, not nested
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
    offset: int = 0,
    path: Optional[str] = None,
    aggregate: bool = False,
    source: Optional[str] = None,
) -> dict:
    """List ALL tickets - both from Linear and local storage.

    Returns MINIMAL summary (~40 tokens/ticket). No descriptions included.
    Use get_ticket(identifier) to fetch full details including description.

    Args:
        state: Filter by state (Backlog, Todo, In Progress, In Review, Done, pending, in_progress, completed)
        label: Filter by label name (Linear tickets only)
        priority: Filter by priority (1=Urgent, 2=High, 3=Medium, 4=Low)
        limit: Maximum tickets to return (default 20, max 100)
        offset: Skip first N tickets for pagination (default 0)
        path: Directory to get context from (defaults to current directory)
        aggregate: If True, scan for all .pm/ configs and aggregate tickets
        source: Filter by source ('linear', 'local', or None for both)

    Returns list of tickets with pagination info.
    """
    if aggregate:
        return _list_tickets_aggregated(state, label, priority, limit, path)

    all_tickets = []

    # Get local tickets from SQLite
    if source != "linear":
        try:
            db, project_id, context = _get_db_for_path(path)
            ticket_manager = LocalTicketManager(db, project_id)

            # Map state to local status if needed
            local_status = None
            if state:
                state_lower = state.lower()
                status_map = {
                    "todo": "pending",
                    "backlog": "pending",
                    "in progress": "in_progress",
                    "in review": "in_progress",
                    "done": "completed",
                }
                local_status = status_map.get(state_lower, state_lower)

            local_tickets = ticket_manager.list(
                status=local_status,
                include_completed=(state and state.lower() in ["done", "completed"]),
            )

            # Format local tickets to match Linear format
            for t in local_tickets:
                # Skip if priority filter doesn't match
                if priority is not None and t.priority != priority:
                    continue

                all_tickets.append({
                    "identifier": t.id[:8],  # Short ID for display
                    "id": t.id,
                    "title": t.title,
                    "state": _local_status_to_state(t.status),
                    "priority": t.priority,
                    "source": "local",
                    "tags": t.tags,
                })
        except Exception:
            pass  # Continue even if local DB fails

    # Get Linear tickets if configured
    if source != "local":
        try:
            client, context, error = _get_client_safe(path)
            if not error and client.config.team_id:
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

                # Add Linear tickets
                for i in issues:
                    formatted = _format_issue_summary(i)
                    formatted["source"] = "linear"
                    all_tickets.append(formatted)
        except Exception:
            pass  # Continue even if Linear fails

    # Sort by priority (highest first) then by identifier
    all_tickets = sorted(all_tickets, key=lambda t: (-(t.get("priority") or 0), t.get("identifier", "")))

    # Apply pagination
    limit = min(limit, 100)  # Cap at 100
    total_count = len(all_tickets)
    paginated_tickets = all_tickets[offset:offset + limit]
    has_more = (offset + limit) < total_count

    return {
        "tickets": paginated_tickets,
        "pagination": {
            "total_count": total_count,
            "showing": len(paginated_tickets),
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
        },
    }


def _local_status_to_state(status: str) -> str:
    """Convert local ticket status to display state."""
    status_map = {
        "pending": "Todo",
        "in_progress": "In Progress",
        "completed": "Done",
        "blocked": "Blocked",
        "canceled": "Canceled",
        "orphaned": "Orphaned",
    }
    return status_map.get(status, status.title())


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


# ============================================================================
# Local Tickets MCP Tools
# ============================================================================


@mcp.tool()
def local_ticket_create(
    title: str,
    description: Optional[str] = None,
    parent_ticket_id: Optional[str] = None,
    priority: int = 2,
    tags: Optional[list[str]] = None,
    status: str = "pending",
    blocks: Optional[list[str]] = None,
    blocked_by: Optional[list[str]] = None,
    path: Optional[str] = None,
) -> dict:
    """Create a local ticket for tracking work.

    Local tickets are stored locally and work fully offline.
    They can optionally be linked to a parent Linear ticket.

    Args:
        title: Ticket title (what needs to be done)
        description: Optional detailed description
        parent_ticket_id: Parent Linear ticket to link (e.g., "SEM-123")
        priority: 0-4, higher = more important (default 2)
        tags: Optional list of tags for categorization
        status: Initial status (pending, in_progress, blocked) - default 'pending'
        blocks: List of ticket IDs this ticket blocks
        blocked_by: List of ticket IDs that block this ticket
        path: Directory to get context from (defaults to current directory)

    Returns created ticket with any linked parent ticket info.

    Example workflow:
    1. Get parent ticket requirements: get_ticket("SEM-45")
    2. Create sub-tickets:
       - local_ticket_create("Implement JWT validation", parent_ticket_id="SEM-45")
       - local_ticket_create("Add refresh token logic", parent_ticket_id="SEM-45", blocked_by=[ticket1_id])
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    # Link to external item if parent_ticket_id provided
    external_item_id = None
    if parent_ticket_id:
        external_item_id = _cache_external_item(db, project_id, parent_ticket_id, path)
        if not external_item_id:
            return {
                "error": "ticket_not_found",
                "message": f"Could not find or cache parent ticket: {parent_ticket_id}",
            }

    # Create the ticket
    ticket_manager = LocalTicketManager(db, project_id)
    ticket = ticket_manager.create(
        title=title,
        description=description,
        parent_ticket_id=external_item_id,
        priority=priority,
        tags=tags,
        status=status,
    )

    # Add dependencies if specified
    dep_manager = DependencyManager(db, project_id)

    if blocks:
        for target_id in blocks:
            dep_manager.add(
                source_id=ticket.id,
                target_id=target_id,
                relation="blocks",
                source_type="local",
                target_type="local",
            )

    if blocked_by:
        for source_id in blocked_by:
            dep_manager.add(
                source_id=source_id,
                target_id=ticket.id,
                relation="blocks",
                source_type="local",
                target_type="local",
            )

    # Re-fetch to get full denormalized data
    ticket = ticket_manager.get(ticket.id)

    return {
        "success": True,
        "ticket": _format_local_ticket(ticket),
    }


@mcp.tool()
def local_ticket_update(
    ticket_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    tags: Optional[list[str]] = None,
    parent_ticket_id: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    """Update a local ticket.

    Args:
        ticket_id: Ticket UUID to update
        title: New title
        description: New description
        status: New status (pending, in_progress, completed, blocked, canceled)
        priority: New priority (0-4)
        tags: New tags list (replaces existing)
        parent_ticket_id: Link to different parent ticket (or empty string to unlink)
        path: Directory to get context from (defaults to current directory)

    Returns updated ticket or error.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    ticket_manager = LocalTicketManager(db, project_id)

    # Check ticket exists
    existing = ticket_manager.get(ticket_id)
    if not existing:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    # Handle parent ticket linking
    external_item_id = None
    if parent_ticket_id is not None:
        if parent_ticket_id == "":
            external_item_id = ""  # Signal to unlink
        else:
            external_item_id = _cache_external_item(db, project_id, parent_ticket_id, path)
            if not external_item_id:
                return {
                    "error": "ticket_not_found",
                    "message": f"Could not find or cache parent ticket: {parent_ticket_id}",
                }

    # Update the ticket
    ticket = ticket_manager.update(
        ticket_id=ticket_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        tags=tags,
        parent_ticket_id=external_item_id,
    )

    return {
        "success": True,
        "ticket": _format_local_ticket(ticket),
    }


@mcp.tool()
def local_ticket_list(
    parent_ticket_id: Optional[str] = None,
    epic_id: Optional[str] = None,
    status: Optional[str] = None,
    include_completed: bool = False,
    limit: int = 20,
    offset: int = 0,
    path: Optional[str] = None,
) -> dict:
    """List local tickets with optional filtering.

    Returns MINIMAL summary by default (~25 tokens/ticket vs ~100+ with full details).
    Use local_ticket_get(ticket_id) to fetch full details including description.

    Args:
        parent_ticket_id: Filter by parent ticket (e.g., "SEM-123")
        epic_id: Filter by epic - shows tickets across ALL parent tickets in that epic!
        status: Filter by status (pending, in_progress, completed, blocked, canceled, orphaned)
        include_completed: Include completed/canceled/orphaned tickets (default False)
        limit: Maximum tickets to return (default 20, max 100)
        offset: Skip first N tickets for pagination (default 0)
        path: Directory to get context from (defaults to current directory)

    Returns list of tickets sorted by priority (highest first), then order.
    Includes pagination info: total_count, has_more, next_offset.

    Epic grouping is powerful: when working on related parent tickets in the same epic,
    you can see all sub-tickets across those parent tickets with epic_id filter.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    ticket_manager = LocalTicketManager(db, project_id)

    # Resolve parent_ticket_id to internal UUID if provided
    external_item_id = None
    if parent_ticket_id:
        ext_manager = ExternalItemsManager(db, project_id)
        external_item_id = ext_manager.get_uuid_for_provider_id(parent_ticket_id)
        if not external_item_id:
            # Try caching first
            external_item_id = _cache_external_item(db, project_id, parent_ticket_id, path)

    # Fetch all matching tickets (we'll paginate in memory for now)
    all_tickets = ticket_manager.list(
        parent_ticket_id=external_item_id,
        epic_id=epic_id,
        status=status,
        include_completed=include_completed,
    )

    # Apply pagination
    limit = min(limit, 100)  # Cap at 100
    total_count = len(all_tickets)
    paginated_tickets = all_tickets[offset:offset + limit]
    has_more = (offset + limit) < total_count

    return {
        "tickets": [_format_local_ticket_summary(t) for t in paginated_tickets],
        "pagination": {
            "total_count": total_count,
            "showing": len(paginated_tickets),
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
        },
    }


@mcp.tool()
def local_ticket_get(ticket_id: str, path: Optional[str] = None) -> dict:
    """Get full details for a single local ticket including description.

    Use this to fetch complete ticket information when you need it.
    For listing multiple tickets, use local_ticket_list() which returns minimal summaries.

    Args:
        ticket_id: Ticket UUID (full or short 8-char prefix)
        path: Directory to get context from (defaults to current directory)

    Returns complete ticket with description, timestamps, parent ticket details.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    ticket_manager = LocalTicketManager(db, project_id)

    # Support short ID lookup (first 8 chars)
    ticket = ticket_manager.get(ticket_id)
    if not ticket and len(ticket_id) == 8:
        # Try to find by prefix
        all_tickets = ticket_manager.list(include_completed=True)
        matches = [t for t in all_tickets if t.id.startswith(ticket_id)]
        if len(matches) == 1:
            ticket = matches[0]
        elif len(matches) > 1:
            return {
                "error": "ambiguous_id",
                "message": f"Multiple tickets match prefix '{ticket_id}'",
                "matches": [{"id": t.id, "title": t.title} for t in matches],
            }

    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    return {"ticket": _format_local_ticket(ticket)}


@mcp.tool()
def local_ticket_delete(ticket_id: str, path: Optional[str] = None) -> dict:
    """Delete a local ticket.

    Also removes any dependencies involving this ticket.

    Args:
        ticket_id: Ticket UUID to delete
        path: Directory to get context from (defaults to current directory)

    Returns success or error.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    ticket_manager = LocalTicketManager(db, project_id)

    # Check ticket exists
    existing = ticket_manager.get(ticket_id)
    if not existing:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    # Delete (cascades to dependencies)
    deleted = ticket_manager.delete(ticket_id)

    return {
        "success": deleted,
        "deleted_ticket_id": ticket_id,
        "deleted_title": existing.title,
    }


# ============================================================================
# Dependency Management MCP Tools
# ============================================================================


@mcp.tool()
def dependency_add(
    source_id: str,
    target_id: str,
    relation: str = "blocks",
    source_type: str = "local",
    target_type: str = "local",
    notes: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    """Add a dependency relationship between items.

    For 'blocks' relation: source blocks target (target can't start until source is done).

    Args:
        source_id: ID of the blocking item (plan UUID or ticket provider ID)
        target_id: ID of the blocked item
        relation: "blocks" or "related_to" (default "blocks")
        source_type: "local" (plan) or "external" (ticket) - default "local"
        target_type: "local" (plan) or "external" (ticket) - default "local"
        notes: Optional notes about the dependency
        path: Directory to get context from (defaults to current directory)

    Example: Plan B can't start until Plan A is done:
        dependency_add(source_id=plan_a_id, target_id=plan_b_id, relation="blocks")
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    # Resolve external IDs if needed
    if source_type == "external":
        ext_manager = ExternalItemsManager(db, project_id)
        uuid = ext_manager.get_uuid_for_provider_id(source_id)
        if not uuid:
            uuid = _cache_external_item(db, project_id, source_id, path)
        if uuid:
            source_id = uuid

    if target_type == "external":
        ext_manager = ExternalItemsManager(db, project_id)
        uuid = ext_manager.get_uuid_for_provider_id(target_id)
        if not uuid:
            uuid = _cache_external_item(db, project_id, target_id, path)
        if uuid:
            target_id = uuid

    dep_manager = DependencyManager(db, project_id)

    dep = dep_manager.add(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
        notes=notes,
    )

    return {
        "success": True,
        "dependency": {
            "id": dep.id,
            "source_id": dep.source_id,
            "source_type": dep.source_type,
            "target_id": dep.target_id,
            "target_type": dep.target_type,
            "relation": dep.relation,
            "notes": dep.notes,
        },
    }


@mcp.tool()
def dependency_remove(
    source_id: str,
    target_id: str,
    relation: Optional[str] = None,
    source_type: str = "local",
    target_type: str = "local",
    path: Optional[str] = None,
) -> dict:
    """Remove a dependency relationship.

    Args:
        source_id: ID of the source item
        target_id: ID of the target item
        relation: Specific relation to remove, or all relations if None
        source_type: "local" or "external" (default "local")
        target_type: "local" or "external" (default "local")
        path: Directory to get context from (defaults to current directory)

    Returns count of removed dependencies.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    dep_manager = DependencyManager(db, project_id)

    count = dep_manager.remove(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
    )

    return {
        "success": True,
        "removed_count": count,
    }


@mcp.tool()
def get_blockers(
    item_id: str,
    item_type: str = "local",
    recursive: bool = False,
    include_resolved: bool = False,
    path: Optional[str] = None,
) -> dict:
    """Get items blocking this one.

    Args:
        item_id: Plan UUID or ticket provider ID
        item_type: "local" (plan) or "external" (ticket) - default "local"
        recursive: Walk the full dependency tree (up to depth 10)
        include_resolved: Include already completed/resolved blockers
        path: Directory to get context from (defaults to current directory)

    Returns list of blocking items with their status.
    Useful to understand why an item can't be started.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    dep_manager = DependencyManager(db, project_id)

    blockers = dep_manager.get_blockers(
        item_id=item_id,
        item_type=item_type,
        recursive=recursive,
        include_resolved=include_resolved,
    )

    formatted = [
        {
            "item_type": b.item_type,
            "item_id": b.item_id,
            "title": b.title,
            "status": b.status,
            "depth": b.depth,
            "resolved": b.resolved,
        }
        for b in blockers
    ]

    unresolved_count = len([b for b in blockers if not b.resolved])

    return {
        "blockers": formatted,
        "count": len(formatted),
        "unresolved_count": unresolved_count,
        "is_blocked": unresolved_count > 0,
    }


@mcp.tool()
def get_ready_work(
    include_local: bool = True,
    limit: int = 5,
    path: Optional[str] = None,
) -> dict:
    """Get unblocked items ready to work on.

    An item is "ready" when:
    - Status is pending or in_progress
    - All blocking dependencies are resolved (completed/done/canceled)

    Args:
        include_local: Include local plans (default True)
        limit: Maximum items to return (default 5)
        path: Directory to get context from (defaults to current directory)

    Returns items sorted by priority (highest first).
    Use this to find what you can work on next!
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return {"error": "database_error", "message": str(e)}

    dep_manager = DependencyManager(db, project_id)

    ready = dep_manager.get_ready_work(
        include_local=include_local,
        limit=limit,
    )

    formatted = [
        {
            "item_type": r.item_type,
            "item_id": r.item_id,
            "title": r.title,
            "status": r.status,
            "priority": r.priority,
            "linked_ticket_id": r.linked_ticket_id,
            "linked_epic_id": r.linked_epic_id,
        }
        for r in ready
    ]

    return {
        "ready_items": formatted,
        "count": len(formatted),
    }


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
