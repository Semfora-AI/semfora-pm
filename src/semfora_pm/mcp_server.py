"""MCP Server for Semfora PM - Linear ticket management.

This MCP server exposes Linear ticket management capabilities to AI assistants,
enabling ticket-first development workflows.

Supports directory-based configuration via .pm/config.json files.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from mcp.server.fastmcp import FastMCP, Context

# ============================================================================
# Client CWD Detection via MCP Roots
# ============================================================================
# The MCP server's cwd is where the Python module runs, NOT the user's cwd.
# We use MCP's list_roots() to get the client's (Claude Code's) workspace roots.

_client_cwd: Optional[Path] = None
_roots_initialized: bool = False
_roots_lock: Optional[asyncio.Lock] = None


def _get_roots_lock() -> asyncio.Lock:
    """Get or create the roots lock (lazy init for thread safety)."""
    global _roots_lock
    if _roots_lock is None:
        _roots_lock = asyncio.Lock()
    return _roots_lock


async def _ensure_roots_initialized(ctx: "Context") -> None:
    """Lazily fetch and cache client roots on first tool call.

    This is called by async tools to initialize the client's working directory
    from MCP roots. The result is cached globally for all subsequent calls.
    """
    global _client_cwd, _roots_initialized

    if _roots_initialized:
        return

    async with _get_roots_lock():
        # Double-check after acquiring lock
        if _roots_initialized:
            return

        try:
            result = await ctx.session.list_roots()
            if result.roots:
                # Take the first root as the default working directory
                uri = str(result.roots[0].uri)
                # FileUrl format: file:///path/to/dir
                if uri.startswith("file://"):
                    # Handle both file:// and file:/// formats
                    path_str = uri.replace("file://", "")
                    _client_cwd = Path(path_str)
                elif uri.startswith("/"):
                    _client_cwd = Path(uri)
        except Exception:
            # list_roots might not be supported by the client
            pass
        finally:
            _roots_initialized = True


def _get_effective_path(path: Optional[str]) -> Optional[Path]:
    """Get effective path using cached client roots or explicit path.

    Priority:
    1. Explicit path parameter (if provided)
    2. Cached client CWD from MCP roots (if initialized)
    3. None (caller should fall back to Path.cwd())
    """
    if path:
        return Path(path)
    return _client_cwd

from .linear_client import AuthenticationError, LinearClient, LinearConfig
from .pm_config import (
    PMContext,
    PMDirectoryInfo,
    resolve_context,
    scan_pm_directories,
    get_context_help_message,
)
from .db import Database
from .tickets import TicketManager
from .dependencies import DependencyManager
from .external_items import (
    ExternalItemsManager,
    normalize_linear_status,
    normalize_linear_priority,
)
# Plans-as-Memory architecture imports
from .plans import PlanManager, PlanSummary
from .memory import MemoryManager, ProjectMemory
from .session import SessionManager, SessionContext
from .toon import Plan, serialize as toon_serialize, get_progress_summary
from .output import format_response, build_pagination, paginate
from .services.sprints import (
    sprint_status as svc_sprint_status,
    sprint_status_aggregated as svc_sprint_status_aggregated,
    sprint_suggest as svc_sprint_suggest,
)
from .services.local_tickets import (
    create_local_ticket as svc_local_ticket_create,
    update_local_ticket as svc_local_ticket_update,
    list_local_tickets as svc_local_ticket_list,
    get_local_ticket as svc_local_ticket_get,
    delete_local_ticket as svc_local_ticket_delete,
)
from .services.dependencies import (
    add_dependency as svc_dependency_add,
    remove_dependency as svc_dependency_remove,
    get_blockers as svc_get_blockers,
    get_ready_work as svc_get_ready_work,
)
from .services.unified_tickets import (
    create_unified_ticket as svc_unified_ticket_create,
    get_unified_ticket as svc_unified_ticket_get,
    list_unified_tickets as svc_unified_ticket_list,
    update_unified_ticket as svc_unified_ticket_update,
    link_unified_ticket_external as svc_unified_ticket_link_external,
    update_unified_ticket_ac as svc_unified_ticket_update_ac,
    add_unified_ticket_ac as svc_unified_ticket_add_ac,
)

# Create the MCP server
mcp = FastMCP(
    "semfora-pm",
    instructions="""Semfora PM - Plans-as-Memory Architecture

## Core Concepts
- **Ticket** = WHAT needs doing (unified: local or Linear)
- **Plan** = HOW to do it (steps, ACs, tools, files)
- **Memory** = Condensed context across sessions

## Quick Reference

| Goal | Tool | Notes |
|------|------|-------|
| **Find work** | `search("query")` | 🔍 Searches plans + local + Linear in ONE call |
| Start work | `session_start` | Loads memory, finds plans |
| Resume work | `session_continue` | Returns to last active plan |
| Create plan | `plan_create` | Auto-activates by default |
| Complete step | `plan_step_complete(index)` | 1-based index |
| Quick fix | `quick_fix_note` | No plan needed |
| What next? | `suggest_next_work` | Priority-sorted |
| End session | `session_end` | Condenses memory |

## Unified Search (USE THIS)

**`search()` is the ONE tool for finding work:**

```
search("auth")                           # Find all auth-related work
search("bug", status="open")             # Open bugs only
search("", source="local")               # All local work
search("", status="active")              # What's in progress now?
search("", tags=["critical"])            # Critical items
search("windows", source="local")        # Local Windows work only
```

**Returns grouped results:** plans (HOW) → local_tickets (WHAT) → linear_tickets (external)

**Status options:** "open" (default), "closed", "active", "all"
**Source options:** None (all), "local", "linear"
**Sort options:** "priority" (default), "updated", "created"

## Workflow Patterns

### New Feature (no ticket)
```
session_start() → unified_ticket_create() → plan_create() → work → session_end()
```

### Continue Existing Work
```
session_continue() → [plan shows current step] → plan_step_complete() → ...
```

### Quick Ad-Hoc Fix
```
quick_fix_note("Fixed null pointer in LoginForm")
```
Or if scope grows: `plan_create()` then `plan_update(ticket_id=...)` later.

### "What Should I Work On?"
```
suggest_next_work() → returns blocked/ready/recommended
```

### Save Plan for Later (Don't Activate)
```
local_ticket_create(title, description) → plan_create(..., activate=False)
```
Creates ticket and plan as DRAFT. Won't become active or interrupt current work.
Use `plan_activate(plan_id)` later when ready to start.

## Pagination (IMPORTANT)
List tools return `pagination: {has_more, next_offset}`.
To get more: call again with `offset=next_offset`.
Example: `list_tickets(offset=20, limit=20)`

## When to Fetch What

**Use the PLAN (not ticket) when:**
- Resuming work (`session_continue` gives you the active plan)
- Working through steps (plan has steps, ACs, tools, files)
- Checking progress (plan tracks completed/pending steps)

**Fetch full TICKET only when:**
- Starting work on a NEW ticket for the first time
- Requirements are unclear and you need the original description
- Plan doesn't exist yet and you need to create one

**Rule of thumb:** If a plan exists, trust the plan. The plan was created
FROM the ticket and contains everything needed to execute.

## Token Efficiency
- List tools return MINIMAL summaries (~30 tokens/item)
- `session_continue` returns current plan in TOON format - use this!
- Only call `get_ticket` when starting fresh or requirements unclear
- Plans in TOON format are already token-optimized (~70% smaller)

## Config
- Uses `.pm/config.json` per directory
- `detect_pm_context` shows active config
- `scan_pm_dirs` finds all configs in tree"""
)


def _get_client_for_path(path: Optional[str] = None) -> tuple[LinearClient, PMContext]:
    """Get configured Linear client for a path.

    Returns (client, context) tuple.
    Raises AuthenticationError if not configured.
    """
    # Use effective path (explicit > cached client roots > None)
    path_obj = _get_effective_path(path)
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
            "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."
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


# ============================================================================
# Token Efficiency Helpers
# ============================================================================

# Maximum characters for description fields in list responses
MAX_DESCRIPTION_LENGTH = 500
# Maximum characters for a single plan step
MAX_STEP_LENGTH = 300
# Recommended step length for best token efficiency
RECOMMENDED_STEP_LENGTH = 150


def _truncate(text: Optional[str], max_length: int = MAX_DESCRIPTION_LENGTH) -> Optional[str]:
    """Truncate text with indicator if too long."""
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def _truncate_with_hint(text: Optional[str], max_length: int, hint: str) -> tuple[Optional[str], Optional[str]]:
    """Truncate text and return (truncated_text, hint_if_truncated)."""
    if not text or len(text) <= max_length:
        return text, None
    return text[:max_length - 3] + "...", hint


def _pagination_hint(has_more: bool, next_offset: Optional[int], tool_name: str) -> Optional[str]:
    """Generate pagination hint for list responses."""
    if not has_more:
        return None
    return f"More results available. Call {tool_name}(offset={next_offset}) to get next page."


def _validate_steps(steps: Optional[list[str]]) -> tuple[list[str], list[str]]:
    """Validate step lengths and return (steps, warnings).

    Returns the steps (possibly unchanged) and any warnings about length.
    Long steps are NOT rejected - just warned about.
    """
    if not steps:
        return [], []

    warnings = []
    for i, step in enumerate(steps):
        if len(step) > MAX_STEP_LENGTH:
            warnings.append(
                f"Step {i+1} is {len(step)} chars (recommended max: {RECOMMENDED_STEP_LENGTH}). "
                f"Consider breaking into smaller steps for better tracking."
            )
        elif len(step) > RECOMMENDED_STEP_LENGTH:
            warnings.append(
                f"Step {i+1} is {len(step)} chars. Steps under {RECOMMENDED_STEP_LENGTH} chars work best."
            )

    return steps, warnings


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
    # Use effective path (explicit > cached client roots > None)
    path_obj = _get_effective_path(path)
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

    TicketManager(db, project_id).upsert_external(
        external_item_id=item.id,
        title=item.title,
        description=item.description,
        status=item.status,
        status_category=item.status_category,
        priority=item.priority,
        labels=item.labels,
    )

    return item.id


@mcp.tool()
def scan_pm_dirs(
    path: Optional[str] = None,
    max_depth: int = 3,
    format: str = "toon",
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

    result = {
        "directories": formatted,
        "count": len(formatted),
        "base_path": str(base_path or Path.cwd()),
    }
    return format_response(result, format)


@mcp.tool()
async def detect_pm_context(
    ctx: Context,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Detect PM context for a path."""
    await _ensure_roots_initialized(ctx)

    path_obj = _get_effective_path(path)
    context = resolve_context(path_obj)

    result = {
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

    return format_response(result, format)
    # Initialize client CWD from MCP roots on first call
    await _ensure_roots_initialized(ctx)

    path_obj = _get_effective_path(path)
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
def check_auth(path: Optional[str] = None, format: str = "toon") -> dict:
    """Check authentication status for a path.

    Args:
        path: Directory to check context for (defaults to current directory)

    Returns authentication status and configuration info.
    """
    path_obj = Path(path) if path else None
    context = resolve_context(path_obj)

    if not context.api_key:
        result = {
            "authenticated": False,
            "help": LinearConfig.get_auth_help_message(),
        }
        return format_response(result, format)

    # Verify API key works
    try:
        config = LinearConfig(api_key=context.api_key)
        client = LinearClient(config)
        teams = client.get_teams()

        result = {
            "authenticated": True,
            "config_source": context.config_source,
            "config_path": str(context.config_path) if context.config_path else None,
            "team_id": context.team_id,
            "team_name": context.team_name,
            "available_teams": [{"id": t["id"], "name": t["name"]} for t in teams],
        }
        return format_response(result, format)
    except Exception as e:
        result = {
            "authenticated": False,
            "error": str(e),
            "help": LinearConfig.get_auth_help_message(),
        }
        return format_response(result, format)


@mcp.tool()
async def sprint_status(
    ctx: Context,
    path: Optional[str] = None,
    aggregate: bool = False,
    limit: int = 20,
    offset: int = 0,
    format: str = "toon",
) -> dict:
    """Get current sprint status showing all active tickets.

    Args:
        path: Directory to get context from (defaults to current directory)
        aggregate: If True, scan for all .pm/ configs and aggregate tickets across
                  all configured teams/projects, deduping when they share the same project.
                  Useful when calling from a base directory containing multiple repos.

    Returns tickets grouped by state: In Progress, In Review, and Todo.
    Use this FIRST before starting any work to see what's currently active.
    """
    # Initialize client CWD from MCP roots on first call
    await _ensure_roots_initialized(ctx)

    if aggregate:
        result = svc_sprint_status_aggregated(Path(path) if path else None, limit=limit, offset=offset)
    else:
        result = svc_sprint_status(Path(path) if path else None, limit=limit, offset=offset)
    return format_response(result, format)




@mcp.tool()
async def get_ticket(
    ctx: Context,
    identifier: str,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
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
    await _ensure_roots_initialized(ctx)
    client, context, error = _get_client_safe(path)
    if error:
        return format_response(error, format)

    issue = client.get_issue_full(identifier)

    if not issue:
        return format_response({"error": f"Ticket not found: {identifier}"}, format)

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

    result = {
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
    return format_response(result, format)


@mcp.tool()
def get_ticket_summary(
    identifier: str,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
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
        return format_response(error, format)

    issue = client.get_issue_by_identifier(identifier)

    if not issue:
        return format_response({"error": "not_found", "message": f"Ticket {identifier} not found"}, format)

    # Truncate title if too long for display
    title = issue.get("title", "")
    if len(title) > 50:
        title = title[:47] + "..."

    # Get assignee name
    assignee = issue.get("assignee")
    assignee_name = assignee.get("name") if assignee else None

    # Return minimal response (<100 tokens for CLI efficiency)
    result = {
        "identifier": issue["identifier"],
        "title": title,
        "state": issue["state"]["name"],
        "priority": _format_priority(issue.get("priority", 0)),
        "assignee": assignee_name,
    }
    return format_response(result, format)


@mcp.tool()
async def list_tickets(
    ctx: Context,
    state: Optional[str] = None,
    label: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    path: Optional[str] = None,
    aggregate: bool = False,
    source: Optional[str] = None,
    format: str = "toon",
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
    await _ensure_roots_initialized(ctx)
    if aggregate:
        result = _list_tickets_aggregated(state, label, priority, limit, path)
        return format_response(result, format)

    all_tickets = []

    # Get local tickets from SQLite
    if source != "linear":
        try:
            db, project_id, context = _get_db_for_path(path)
            ticket_manager = TicketManager(db, project_id)

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
                    "blocked": "blocked",
                    "canceled": "canceled",
                    "cancelled": "canceled",
                }
                local_status = status_map.get(state_lower, state_lower)

            local_tickets = ticket_manager.list_local(
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

    result = {
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

    # Add pagination hint for AI
    hint = _pagination_hint(has_more, offset + limit if has_more else None, "list_tickets")
    if hint:
        result["_hint"] = hint

    return format_response(result, format)


def _local_status_to_state(status: str) -> str:
    """Convert local ticket status to display state."""
    status_map = {
        "pending": "Todo",
        "in_progress": "In Progress",
        "completed": "Done",
        "done": "Done",
        "blocked": "Blocked",
        "canceled": "Canceled",
        "cancelled": "Canceled",
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
    limit: int = 20,
    offset: int = 0,
    format: str = "toon",
) -> dict:
    """Suggest tickets for next sprint based on priority and points budget.

    Args:
        points: Target story points for sprint (default 20)
        label: Optional label to filter by (e.g., 'phase-2.5')
        path: Directory to get context from (defaults to current directory)

    Returns suggested tickets that fit the point budget, sorted by priority.
    """
    result = svc_sprint_suggest(points=points, label=label, limit=limit, offset=offset, path=Path(path) if path else None)
    return format_response(result, format)


@mcp.tool()
async def search(
    ctx: Context,
    query: str,
    source: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "priority",
    tags: Optional[list[str]] = None,
    limit: int = 10,
    offset: int = 0,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """🔍 UNIFIED SEARCH: Search plans, local tickets, AND Linear tickets.

    Searches EVERYTHING by default - one tool to find all work items.
    Results are grouped by type: plans first (HOW), then tickets (WHAT).

    Args:
        query: Search text to match against title and description
        source: Filter by source - "local", "linear", or None for ALL (default)
        status: Filter by status:
            - "open" (default): Active/pending/in-progress items
            - "closed": Completed/canceled/abandoned items
            - "active": Currently being worked on (in_progress, active)
            - "all": Everything regardless of status
        sort_by: "priority" (default), "updated", or "created"
        tags: Filter by tags (local items only)
        limit: Max results per category (default 10)
        offset: Skip first N results for pagination (default 0)
        path: Directory to get context from (defaults to current directory)

    Returns grouped results:
        - plans: Implementation plans (HOW to do work)
        - local_tickets: Local tickets (WHAT to do)
        - linear_tickets: Linear tickets (external requirements)
        - pagination: {has_more, next_offset}

    Examples:
        search("auth")  # Find all auth-related work
        search("bug", status="open")  # Open bugs only
        search("", source="local", status="active")  # What am I working on now?
        search("", tags=["critical"])  # All critical items
    """
    # Initialize client CWD from MCP roots on first call
    await _ensure_roots_initialized(ctx)

    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    # Normalize status filter
    status = status or "open"
    status_filters = {
        "open": {
            "plans": ["draft", "active", "paused"],
            "local": ["pending", "in_progress", "blocked"],
            "linear": ["Backlog", "Todo", "In Progress", "In Review"],
        },
        "closed": {
            "plans": ["completed", "abandoned"],
            "local": ["completed", "canceled", "orphaned"],
            "linear": ["Done", "Canceled"],
        },
        "active": {
            "plans": ["active"],
            "local": ["in_progress"],
            "linear": ["In Progress"],
        },
        "all": {
            "plans": None,  # No filter
            "local": None,
            "linear": None,
        },
    }

    if status not in status_filters:
        return {"error": "invalid_status", "message": f"status must be one of: open, closed, active, all"}

    filters = status_filters[status]
    results = {
        "plans": [],
        "local_tickets": [],
        "linear_tickets": [],
        "query": query,
        "filters": {"source": source or "all", "status": status, "sort_by": sort_by},
    }

    search_pattern = f"%{query}%" if query else "%"

    # === SEARCH PLANS ===
    if source in (None, "local"):
        plan_mgr = PlanManager(db, project_id)

        # Build status filter for plans
        plan_status_filter = filters["plans"]

        # Use plan search if we have a query, otherwise list
        if query:
            plan_results = plan_mgr.search(query, limit=limit + offset)
        else:
            plan_results = plan_mgr.list(status=None, limit=limit + offset)

        # Filter by status if needed
        if plan_status_filter:
            plan_results = [p for p in plan_results if p.status in plan_status_filter]

        # Apply offset and limit
        plan_results = plan_results[offset:offset + limit]

        # Sort
        if sort_by == "priority":
            # Plans don't have priority, sort by status (active first)
            status_order = {"active": 0, "paused": 1, "draft": 2, "completed": 3, "abandoned": 4}
            plan_results.sort(key=lambda p: status_order.get(p.status, 5))
        elif sort_by == "updated":
            plan_results.sort(key=lambda p: p.updated_at or "", reverse=True)
        elif sort_by == "created":
            plan_results.sort(key=lambda p: p.created_at or "", reverse=True)

        results["plans"] = [
            {
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "ticket_id": p.ticket_id,
                "completed_steps": p.completed_steps,
                "step_count": p.step_count,
                "_type": "plan",
            }
            for p in plan_results
        ]

    # === SEARCH LOCAL TICKETS ===
    if source in (None, "local"):
        local_status_filter = filters["local"]

        # Build query
        sql = """
            SELECT t.id, t.title, t.status, t.priority, t.tags,
                   t.parent_ticket_id, t.parent_external_item_id,
                   t.updated_at, t.created_at,
                   pe.provider_id as parent_external_id
            FROM tickets t
            LEFT JOIN external_items pe ON t.parent_external_item_id = pe.id
            WHERE t.project_id = ? AND t.source = 'local'
              AND (t.title LIKE ? OR t.description LIKE ?)
        """
        params = [project_id, search_pattern, search_pattern]

        if local_status_filter:
            placeholders = ",".join("?" * len(local_status_filter))
            sql += f" AND status IN ({placeholders})"
            params.extend(local_status_filter)

        if tags:
            for tag in tags:
                sql += " AND tags LIKE ?"
                params.append(f"%{tag}%")

        # Sort
        if sort_by == "priority":
            sql += " ORDER BY priority DESC, updated_at DESC"
        elif sort_by == "updated":
            sql += " ORDER BY updated_at DESC"
        elif sort_by == "created":
            sql += " ORDER BY created_at DESC"

        sql += f" LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with db.transaction() as conn:
            rows = conn.execute(sql, params).fetchall()

        formatted = []
        for row in rows:
            tags_value = json.loads(row[4]) if row[4] else []
            formatted.append(
                {
                    "id": row[0][:8],
                    "full_id": row[0],
                    "title": row[1],
                    "status": row[2],
                    "priority": row[3],
                    "tags": tags_value,
                    "parent_ticket_id": row[5],
                    "parent_external_item_id": row[6],
                    "parent_external_id": row[9],
                    "_type": "local_ticket",
                }
            )

        results["local_tickets"] = formatted

    # === SEARCH LINEAR TICKETS ===
    if source in (None, "linear"):
        client, linear_context, error = _get_client_safe(path)
        if not error and client:
            try:
                if query:
                    linear_results = client.search_issues(query)
                else:
                    # Get recent issues if no query
                    linear_results = client.get_team_issues(limit=limit + offset)

                # Filter by status
                linear_status_filter = filters["linear"]
                if linear_status_filter:
                    linear_results = [
                        i for i in linear_results
                        if i.get("state", {}).get("name") in linear_status_filter
                    ]

                # Apply offset and limit
                linear_results = linear_results[offset:offset + limit]

                # Sort by priority if requested
                if sort_by == "priority":
                    linear_results.sort(key=lambda i: i.get("priority") or 0, reverse=True)

                results["linear_tickets"] = [
                    {
                        "id": i.get("identifier"),
                        "title": i.get("title"),
                        "status": i.get("state", {}).get("name"),
                        "priority": i.get("priority"),
                        "labels": [l.get("name") for l in i.get("labels", {}).get("nodes", [])],
                        "_type": "linear_ticket",
                    }
                    for i in linear_results
                ]
            except Exception:
                # Linear search failed, continue with local results
                results["_linear_error"] = "Linear search unavailable"

    # === PAGINATION ===
    total_found = len(results["plans"]) + len(results["local_tickets"]) + len(results["linear_tickets"])
    has_more = total_found == limit  # Approximate - at least one category hit limit
    results["pagination"] = {
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }

    # === HINT ===
    if total_found == 0:
        results["_hint"] = f"No results for '{query}'. Try status='all' or different query."
    else:
        type_counts = []
        if results["plans"]:
            type_counts.append(f"{len(results['plans'])} plans")
        if results["local_tickets"]:
            type_counts.append(f"{len(results['local_tickets'])} local tickets")
        if results["linear_tickets"]:
            type_counts.append(f"{len(results['linear_tickets'])} Linear tickets")
        results["_hint"] = f"Found {', '.join(type_counts)}. Use plan_get/local_ticket_get/get_ticket for details."

    return format_response(results, format)


@mcp.tool()
def search_tickets(
    query: str,
    limit: int = 10,
    offset: int = 0,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Search for tickets by text query.

    NOTE: Consider using search() instead - it searches plans, local tickets,
    AND Linear tickets in one call with filtering options.

    Args:
        query: Search text to match against title and description
        limit: Maximum results to return (default 10)
        path: Directory to get context from (defaults to current directory)

    Returns matching tickets.
    """
    client, context, error = _get_client_safe(path)
    if error:
        return format_response(error, format)

    results = client.search_issues(query)

    if not results:
        return format_response({"tickets": [], "pagination": {"total_count": 0, "offset": offset, "limit": limit}}, format)

    summaries = [_format_issue_summary(i) for i in results]
    page, pagination = paginate(summaries, limit, offset)

    result = {
        "tickets": page,
        "pagination": pagination,
    }
    return format_response(result, format)


@mcp.tool()
def update_ticket_status(
    identifier: str,
    state: str,
    path: Optional[str] = None,
    format: str = "toon",
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
        return format_response(error, format)

    # Get issue to find team
    issue = client.get_issue_by_identifier(identifier)
    if not issue:
        return format_response({"error": f"Ticket not found: {identifier}"}, format)

    # Use configured team_id or try to get from issue
    team_id = client.config.team_id
    if not team_id:
        return format_response({"error": "No team configured"}, format)

    # Get state ID
    states = client.get_team_states(team_id)
    state_id = states.get(state)

    if not state_id:
        available = list(states.keys())
        return format_response({"error": f"Invalid state '{state}'. Available: {available}"}, format)

    # Update the issue
    result = client.update_issue(issue["id"], state_id=state_id)

    result = {
        "success": True,
        "identifier": identifier,
        "new_state": state,
        "url": result.get("url"),
    }
    return format_response(result, format)


@mcp.tool()
def get_related_tickets(
    identifier: str,
    path: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    format: str = "toon",
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
        return format_response(error, format)

    issue = client.get_issue_full(identifier)

    if not issue:
        return format_response({"error": f"Ticket not found: {identifier}"}, format)

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

    blocks, blocks_pagination = paginate(get_relation_details("blocks"), limit, offset)
    blocked_by, blocked_by_pagination = paginate(get_relation_details("blocked"), limit, offset)
    related, related_pagination = paginate(get_relation_details("related"), limit, offset)
    sub_issues_page, sub_issues_pagination = paginate(sub_list, limit, offset)

    result = {
        "identifier": identifier,
        "title": issue["title"],
        "blocks": blocks,
        "blocked_by": blocked_by,
        "related": related,
        "parent": parent_info,
        "sub_issues": sub_issues_page,
        "pagination": {
            "blocks": blocks_pagination,
            "blocked_by": blocked_by_pagination,
            "related": related_pagination,
            "sub_issues": sub_issues_pagination,
        },
    }
    return format_response(result, format)


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
    format: str = "toon",
) -> dict:
    """Create a local ticket for tracking work.

    Local tickets are stored locally and work fully offline.
    They can optionally be linked to a parent local ticket or Linear ticket.

    Args:
        title: Ticket title (what needs to be done)
        description: Optional detailed description
        parent_ticket_id: Parent local ticket ID or Linear ticket (e.g., UUID or "SEM-123")
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
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_manager = TicketManager(db, project_id)
    ext_manager = ExternalItemsManager(db, project_id)

    result = svc_local_ticket_create(
        ticket_manager,
        ext_manager,
        title=title,
        description=description,
        parent_ticket_id=parent_ticket_id,
        priority=priority,
        tags=tags,
        status=status,
        cache_external=lambda pid: _cache_external_item(db, project_id, pid, path),
    )

    if blocks or blocked_by:
        dep_manager = DependencyManager(db, project_id)
        for target_id in blocks or []:
            dep_manager.add(
                source_id=result["ticket"]["id"],
                target_id=target_id,
                relation="blocks",
                source_type="local",
                target_type="local",
            )
        for source_id in blocked_by or []:
            dep_manager.add(
                source_id=source_id,
                target_id=result["ticket"]["id"],
                relation="blocks",
                source_type="local",
                target_type="local",
            )

    return format_response(result, format)


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
    format: str = "toon",
) -> dict:
    """Update a local ticket.

    Args:
        ticket_id: Ticket UUID to update
        title: New title
        description: New description
        status: New status (pending, in_progress, completed, blocked, canceled)
        priority: New priority (0-4)
        tags: New tags list (replaces existing)
        parent_ticket_id: Link to different parent ticket (local ID or Linear ID, empty string to unlink)
        path: Directory to get context from (defaults to current directory)

    Returns updated ticket or error.
    """
    try:
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_manager = TicketManager(db, project_id)
    ext_manager = ExternalItemsManager(db, project_id)

    result = svc_local_ticket_update(
        ticket_manager,
        ext_manager,
        ticket_id=ticket_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        tags=tags,
        parent_ticket_id=parent_ticket_id,
        cache_external=lambda pid: _cache_external_item(db, project_id, pid, path),
    )

    return format_response(result, format)


@mcp.tool()
async def local_ticket_list(
    ctx: Context,
    parent_ticket_id: Optional[str] = None,
    epic_id: Optional[str] = None,
    status: Optional[str] = None,
    include_completed: bool = False,
    limit: int = 20,
    offset: int = 0,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """List local tickets with optional filtering.

    Returns MINIMAL summary by default (~25 tokens/ticket vs ~100+ with full details).
    Use local_ticket_get(ticket_id) to fetch full details including description.

    Args:
        parent_ticket_id: Filter by parent ticket (local ID or Linear ID, e.g., UUID or "SEM-123")
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
    await _ensure_roots_initialized(ctx)
    try:
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_manager = TicketManager(db, project_id)
    ext_manager = ExternalItemsManager(db, project_id)

    result = svc_local_ticket_list(
        ticket_manager,
        ext_manager,
        parent_ticket_id=parent_ticket_id,
        epic_id=epic_id,
        status=status,
        include_completed=include_completed,
        limit=limit,
        offset=offset,
        cache_external=lambda pid: _cache_external_item(db, project_id, pid, path),
    )
    return format_response(result, format)


@mcp.tool()
def local_ticket_get(ticket_id: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Get full details for a single local ticket including description.

    Use this to fetch complete ticket information when you need it.
    For listing multiple tickets, use local_ticket_list() which returns minimal summaries.

    Args:
        ticket_id: Ticket UUID (full or short 8-char prefix)
        path: Directory to get context from (defaults to current directory)

    Returns complete ticket with description, timestamps, parent ticket details.
    """
    try:
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_manager = TicketManager(db, project_id)
    result = svc_local_ticket_get(ticket_manager, ticket_id)
    return format_response(result, format)


@mcp.tool()
def local_ticket_delete(ticket_id: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Delete a local ticket.

    Also removes any dependencies involving this ticket.

    Args:
        ticket_id: Ticket UUID to delete
        path: Directory to get context from (defaults to current directory)

    Returns success or error.
    """
    try:
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_manager = TicketManager(db, project_id)
    result = svc_local_ticket_delete(ticket_manager, ticket_id)
    return format_response(result, format)


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
    format: str = "toon",
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
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    dep_manager = DependencyManager(db, project_id)
    ext_manager = ExternalItemsManager(db, project_id)

    result = svc_dependency_add(
        dep_manager,
        ext_manager,
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
        notes=notes,
        cache_external=lambda pid: _cache_external_item(db, project_id, pid, path),
    )
    return format_response(result, format)


@mcp.tool()
def dependency_remove(
    source_id: str,
    target_id: str,
    relation: Optional[str] = None,
    source_type: str = "local",
    target_type: str = "local",
    path: Optional[str] = None,
    format: str = "toon",
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
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    dep_manager = DependencyManager(db, project_id)
    result = svc_dependency_remove(
        dep_manager,
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
    )
    return format_response(result, format)


@mcp.tool()
def get_blockers(
    item_id: str,
    item_type: str = "local",
    recursive: bool = False,
    include_resolved: bool = False,
    path: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    format: str = "toon",
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
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    dep_manager = DependencyManager(db, project_id)
    result = svc_get_blockers(
        dep_manager,
        item_id=item_id,
        item_type=item_type,
        recursive=recursive,
        include_resolved=include_resolved,
        limit=limit,
        offset=offset,
    )
    return format_response(result, format)


@mcp.tool()
async def get_ready_work(
    ctx: Context,
    include_local: bool = True,
    limit: int = 5,
    path: Optional[str] = None,
    offset: int = 0,
    format: str = "toon",
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
    await _ensure_roots_initialized(ctx)
    try:
        db, project_id, _ = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    dep_manager = DependencyManager(db, project_id)
    result = svc_get_ready_work(
        dep_manager,
        include_local=include_local,
        limit=limit,
        offset=offset,
    )
    return format_response(result, format)


# ============================================================================
# Plans-as-Memory Architecture MCP Tools
# ============================================================================


# --- Session Management ---


@mcp.tool()
async def session_start(
    mcp_ctx: Context,
    ticket_id: Optional[str] = None,
    query: Optional[str] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Start a new session and load memory context.

    If ticket_id is provided, looks for plans related to that ticket.
    If query is provided, searches for matching plans.
    Otherwise, returns the current state from memory.

    Args:
        ticket_id: Optional ticket to work on (e.g., "SEM-45")
        query: Optional search query for finding relevant plans
        path: Directory to get context from (defaults to current directory)

    Returns:
        SessionContext with memory, current plan, matching plans, and suggestions.

    Use this FIRST when starting work to understand the current state.
    """
    # Initialize client CWD from MCP roots on first call
    await _ensure_roots_initialized(mcp_ctx)

    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    ctx = session_mgr.start(ticket_id=ticket_id, query=query)

    # Format the response
    result = {
        "has_active_work": ctx.has_active_work,
        "suggestions": ctx.suggestions,
        "tools_available": ctx.tools_available,
        "key_files": ctx.key_files,
    }

    # Memory summary
    result["memory"] = {
        "current_ticket_id": ctx.memory.current_ticket_id,
        "current_ticket_title": ctx.memory.current_ticket_title,
        "current_plan_id": ctx.memory.current_plan_id,
        "current_plan_title": ctx.memory.current_plan_title,
        "current_plan_status": ctx.memory.current_plan_status,
        "current_step": ctx.memory.current_step,
        "completed_steps": ctx.memory.completed_steps,
        "total_steps": ctx.memory.total_steps,
        "blockers": ctx.memory.blockers,
        "discoveries_count": len(ctx.memory.discoveries),
        "last_session": ctx.memory.last_session_end,
    }

    # Current plan if active
    if ctx.current_plan:
        progress = get_progress_summary(ctx.current_plan)
        result["current_plan"] = {
            "id": ctx.current_plan_id,
            "title": ctx.current_plan.title,
            "status": ctx.current_plan.status,
            "progress": progress,
            "toon": toon_serialize(ctx.current_plan),
        }

    # Matching plans
    if ctx.matching_plans:
        result["matching_plans"] = [
            {
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "ticket_id": p.ticket_id,
                "steps_completed": p.steps_completed,
                "steps_total": p.steps_total,
            }
            for p in ctx.matching_plans
        ]

    return format_response(result, format)


@mcp.tool()
def session_continue(path: Optional[str] = None, format: str = "toon") -> dict:
    """Continue from the last active plan.

    This is the "continue" command - resume exactly where you left off.

    Args:
        path: Directory to get context from (defaults to current directory)

    Returns:
        SessionContext with the last active plan loaded.

    Use this when resuming work after a break.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    ctx = session_mgr.continue_session()

    result = {
        "has_active_work": ctx.has_active_work,
        "suggestions": ctx.suggestions,
    }

    if ctx.current_plan:
        progress = get_progress_summary(ctx.current_plan)
        result["current_plan"] = {
            "id": ctx.current_plan_id,
            "title": ctx.current_plan.title,
            "ticket_id": ctx.current_ticket_id,
            "status": ctx.current_plan.status,
            "progress": progress,
            "toon": toon_serialize(ctx.current_plan),
        }

    return format_response(result, format)


@mcp.tool()
def session_end(
    summary: Optional[str] = None,
    outcome: str = "success",
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """End the current session.

    Condenses memory, updates plan status if needed, and returns a summary.

    Args:
        summary: Optional summary of what was accomplished
        outcome: "success", "blocked", or "abandoned"
        path: Directory to get context from (defaults to current directory)

    Returns:
        SessionSummary with progress info and next step.

    Use this when finishing work for the day or switching tasks.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    result = session_mgr.end(summary=summary, outcome=outcome)

    result = {
        "steps_completed": result.steps_completed,
        "steps_remaining": result.steps_remaining,
        "blockers": result.blockers,
        "discoveries_added": result.discoveries_added,
        "next_step": result.next_step,
        "plan_status": result.plan_status,
    }
    return format_response(result, format)


# --- Plan Management ---


@mcp.tool()
def plan_create(
    title: str,
    ticket_id: Optional[str] = None,
    steps: Optional[list[str]] = None,
    acceptance_criteria: Optional[list[str]] = None,
    tools: Optional[list[str]] = None,
    files: Optional[list[str]] = None,
    activate: bool = True,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Create a new implementation plan.

    Plans define HOW to accomplish a ticket. Multiple plans can exist per ticket.

    Args:
        title: Plan title (e.g., "Implement JWT authentication")
        ticket_id: Optional ticket this plan addresses (e.g., "SEM-45")
        steps: List of step descriptions
        acceptance_criteria: List of AC text to track
        tools: MCP tools this plan will use
        files: Key files this plan will touch
        activate: Set as active plan immediately (default True)
        path: Directory to get context from (defaults to current directory)

    Returns:
        Created plan in TOON format with ID.

    Example:
        plan_create(
            title="Implement JWT authentication",
            ticket_id="SEM-45",
            steps=["Create JWTService class", "Add validation middleware", "Write tests"],
            acceptance_criteria=["Validate tokens", "Support refresh"],
            tools=["mcp__semfora-engine__search", "Edit", "Bash"],
            files=["src/auth/jwt.py", "tests/test_auth.py"],
        )
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    # Validate step lengths and generate warnings
    validated_steps, step_warnings = _validate_steps(steps)

    session_mgr = SessionManager(db, project_id)

    if activate:
        plan_id, plan = session_mgr.create_and_activate_plan(
            title=title,
            ticket_id=ticket_id,
            steps=steps,
            acceptance_criteria=acceptance_criteria,
            tools=tools,
            files=files,
        )
    else:
        plan_mgr = PlanManager(db, project_id)
        plan_id = plan_mgr.create(
            title=title,
            ticket_id=ticket_id,
            steps=steps,
            acceptance_criteria=acceptance_criteria,
            tools=tools,
            files=files,
        )
        plan = plan_mgr.get(plan_id)

    result = {
        "success": True,
        "plan_id": plan_id,
        "title": plan.title,
        "status": plan.status,
        "progress": get_progress_summary(plan),
        "toon": toon_serialize(plan),
    }
    # Include step length warnings for AI to consider breaking up long steps
    if step_warnings:
        result["_warnings"] = step_warnings
    return format_response(result, format)


@mcp.tool()
def plan_activate(plan_id: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Activate a plan and set it as current.

    Args:
        plan_id: Plan UUID to activate
        path: Directory to get context from (defaults to current directory)

    Returns:
        Activated plan details.

    Use this to switch to a different plan.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    plan = session_mgr.activate_plan(plan_id)

    if not plan:
        return format_response({"error": "not_found", "message": f"Plan not found: {plan_id}"}, format)

    result = {
        "success": True,
        "plan_id": plan_id,
        "title": plan.title,
        "status": plan.status,
        "progress": get_progress_summary(plan),
        "toon": toon_serialize(plan),
    }
    return format_response(result, format)


@mcp.tool()
async def plan_get(ctx: Context, plan_id: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Get a plan by ID.

    Args:
        plan_id: Plan UUID
        path: Directory to get context from (defaults to current directory)

    Returns:
        Plan details in TOON format.
    """
    # Initialize client CWD from MCP roots on first call
    await _ensure_roots_initialized(ctx)

    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    plan_mgr = PlanManager(db, project_id)
    plan = plan_mgr.get(plan_id)

    if not plan:
        return format_response({"error": "not_found", "message": f"Plan not found: {plan_id}"}, format)

    result = {
        "plan_id": plan_id,
        "title": plan.title,
        "ticket_id": plan.ticket_id,
        "status": plan.status,
        "progress": get_progress_summary(plan),
        "toon": toon_serialize(plan),
    }
    return format_response(result, format)


@mcp.tool()
async def plan_list(
    ctx: Context,
    ticket_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """List plans with optional filtering.

    Args:
        ticket_id: Filter by ticket (e.g., "SEM-45")
        status: Filter by status (draft, active, paused, completed, abandoned)
        limit: Maximum plans to return (default 20, max 50)
        offset: Skip first N plans for pagination (default 0)
        path: Directory to get context from (defaults to current directory)

    Returns:
        List of plan summaries with pagination info.
    """
    await _ensure_roots_initialized(ctx)
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    plan_mgr = PlanManager(db, project_id)
    limit = min(limit, 50)
    total_count = plan_mgr.count(ticket_id=ticket_id, status=status)
    paginated_plans = plan_mgr.list(ticket_id=ticket_id, status=status, limit=limit, offset=offset)

    result = {
        "plans": [
            {
                "id": p.id,
                "title": p.title,
                "status": p.status,
                "ticket_id": p.ticket_id,
                "completed_steps": p.completed_steps,
                "step_count": p.step_count,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in paginated_plans
        ],
        "pagination": build_pagination(total_count, limit, offset),
    }

    # Add pagination hint for AI
    hint = _pagination_hint(
        result["pagination"]["has_more"],
        result["pagination"]["next_offset"],
        "plan_list",
    )
    if hint:
        result["_hint"] = hint

    return format_response(result, format)


@mcp.tool()
def plan_step_complete(
    step_index: int,
    output: Optional[str] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Mark a step as completed.

    Args:
        step_index: Step index (1-based)
        output: Optional output/result from the step
        path: Directory to get context from (defaults to current directory)

    Returns:
        Updated plan progress.

    Use this as you complete each step in the plan.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    session_mgr.record_step_complete(step_index, output)

    # Get updated status
    status = session_mgr.get_status()

    result = {
        "success": True,
        "step_completed": step_index,
        "progress": status.get("active_plan", {}).get("progress"),
    }
    return format_response(result, format)


@mcp.tool()
def plan_step_skip(
    step_index: int,
    reason: str,
    approved: bool = False,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Skip a step with deviation tracking.

    Args:
        step_index: Step index (1-based)
        reason: Why the step is being skipped
        approved: Whether user approved the skip (default False)
        path: Directory to get context from (defaults to current directory)

    Returns:
        Updated plan progress.

    Use this when a step needs to be skipped or approach changed.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    session_mgr = SessionManager(db, project_id)
    session_mgr.record_deviation(step_index, reason, approved)

    # Get updated status
    status = session_mgr.get_status()

    result = {
        "success": True,
        "step_skipped": step_index,
        "reason": reason,
        "approved": approved,
        "progress": status.get("active_plan", {}).get("progress"),
    }
    return format_response(result, format)


@mcp.tool()
def plan_deviate(
    reason: str,
    new_steps: Optional[list[str]] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Record a deviation from the current plan.

    Args:
        reason: Why the deviation is happening
        new_steps: Optional new steps to add
        path: Directory to get context from (defaults to current directory)

    Returns:
        Updated plan.

    Use this when changing approach significantly from the original plan.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    # Add discovery for the deviation
    session_mgr = SessionManager(db, project_id)
    session_mgr.add_discovery(f"Plan deviation: {reason}", importance=4)

    # Add new steps if provided
    memory = session_mgr.memory_mgr.get()
    if memory.current_plan_id and new_steps:
        plan_mgr = PlanManager(db, project_id)
        for step_desc in new_steps:
            plan_mgr.add_step(memory.current_plan_id, step_desc)

        plan = plan_mgr.get(memory.current_plan_id)
        result = {
            "success": True,
            "reason": reason,
            "new_steps_added": len(new_steps),
            "plan": {
                "id": memory.current_plan_id,
                "title": plan.title,
                "progress": get_progress_summary(plan),
                "toon": toon_serialize(plan),
            },
        }
        return format_response(result, format)

    result = {
        "success": True,
        "reason": reason,
        "deviation_logged": True,
    }
    return format_response(result, format)


@mcp.tool()
def plan_complete(plan_id: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Mark a plan as completed.

    Args:
        plan_id: Plan UUID to complete
        path: Directory to get context from (defaults to current directory)

    Returns:
        Completion status.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    plan_mgr = PlanManager(db, project_id)
    success = plan_mgr.complete(plan_id)

    if not success:
        return format_response({"error": "not_found", "message": f"Plan not found: {plan_id}"}, format)

    return format_response({"success": True, "plan_id": plan_id, "status": "completed"}, format)


@mcp.tool()
def plan_abandon(
    plan_id: str,
    reason: Optional[str] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Abandon a plan.

    Args:
        plan_id: Plan UUID to abandon
        reason: Why the plan is being abandoned
        path: Directory to get context from (defaults to current directory)

    Returns:
        Abandonment status.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    plan_mgr = PlanManager(db, project_id)
    success = plan_mgr.abandon(plan_id, reason)

    if not success:
        return format_response({"error": "not_found", "message": f"Plan not found: {plan_id}"}, format)

    return format_response({"success": True, "plan_id": plan_id, "status": "abandoned", "reason": reason}, format)


@mcp.tool()
def suggest_next_work(path: Optional[str] = None, format: str = "toon") -> dict:
    """Suggest what to work on next based on priorities and blockers.

    Analyzes all active/paused plans and returns recommendations
    sorted by priority, with blocked items separated.

    Use this when user asks "what should I work on?" or to help
    prioritize between multiple in-flight tasks.

    Args:
        path: Directory to get context from (defaults to current directory)

    Returns:
        - blocked: List of blocked work items
        - ready: List of unblocked items sorted by priority
        - recommended: The single best item to work on
        - summary: Human-readable summary
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    from .session import SessionManager

    session_mgr = SessionManager(db, project_id)
    result = session_mgr.suggest_next_work()

    # Format for JSON output
    def format_suggestion(s):
        return {
            "plan_id": s.plan_id,
            "plan_title": s.plan_title,
            "ticket_id": s.ticket_id,
            "ticket_title": s.ticket_title,
            "priority": s.priority,
            "progress": s.progress,
            "status": s.status,
            "reason": s.reason,
        }

    result = {
        "blocked": [format_suggestion(s) for s in result["blocked"]],
        "ready": [format_suggestion(s) for s in result["ready"]],
        "recommended": format_suggestion(result["recommended"]) if result["recommended"] else None,
        "summary": result["summary"],
    }
    return format_response(result, format)


@mcp.tool()
def plan_update(
    plan_id: str,
    ticket_id: Optional[str] = None,
    title: Optional[str] = None,
    tools: Optional[list[str]] = None,
    files: Optional[list[str]] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Update a plan's metadata.

    Use this to:
    - Retroactively link a plan to a ticket (when a quick fix becomes bigger)
    - Update the plan title
    - Add/change tools or files list

    Args:
        plan_id: Plan to update
        ticket_id: New ticket ID to link (empty string to unlink)
        title: New title
        tools: New tools list
        files: New files list
        path: Directory to get context from (defaults to current directory)

    Returns:
        Updated plan details.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    from .plans import PlanManager
    from .toon import get_progress_summary

    plan_mgr = PlanManager(db, project_id)
    plan = plan_mgr.update(
        plan_id,
        ticket_id=ticket_id,
        title=title,
        tools=tools,
        files=files,
    )

    if not plan:
        return format_response({"error": "not_found", "message": f"Plan {plan_id} not found"}, format)

    progress = get_progress_summary(plan)
    result = {
        "success": True,
        "plan_id": plan_id,
        "title": plan.title,
        "ticket_id": plan.ticket_id,
        "status": plan.status,
        "tools": plan.tools,
        "files": plan.files,
        "progress": progress,
    }
    return format_response(result, format)


@mcp.tool()
def quick_fix_note(
    description: str,
    importance: int = 2,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Record a quick fix without creating a plan.

    Use this for small fixes that don't warrant full plan tracking.
    The fix is noted in memory so context isn't lost.

    Perfect for: "I just want to fix this bug quickly, not part of current work"

    Args:
        description: What was fixed
        importance: 1-5 (default 2 = normal)
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation of the note added.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    from .session import SessionManager

    session_mgr = SessionManager(db, project_id)
    session_mgr.quick_fix_note(description, importance)

    result = {
        "success": True,
        "message": f"Quick fix noted: {description}",
        "importance": importance,
    }
    return format_response(result, format)


# --- Memory Access ---


@mcp.tool()
def memory_get(path: Optional[str] = None, format: str = "toon") -> dict:
    """Get the current project memory.

    Returns condensed context from previous sessions including:
    - Current work (ticket, plan)
    - Progress (steps completed, blockers)
    - Discoveries (patterns learned, decisions made)
    - Reference (key files, tools)

    Args:
        path: Directory to get context from (defaults to current directory)

    Returns:
        ProjectMemory contents.

    Use this to understand the current state before starting work.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory = memory_mgr.get()

    result = {
        "current_work": {
            "ticket_id": memory.current_ticket_id,
            "ticket_title": memory.current_ticket_title,
            "plan_id": memory.current_plan_id,
            "plan_title": memory.current_plan_title,
            "plan_status": memory.current_plan_status,
        },
        "progress": {
            "current_step": memory.current_step,
            "completed_steps": memory.completed_steps,
            "total_steps": memory.total_steps,
            "blockers": memory.blockers,
        },
        "discoveries": [
            {
                "content": d.content,
                "importance": d.importance,
                "created_at": d.created_at,
            }
            for d in memory.discoveries
        ],
        "reference": {
            "key_files": memory.key_files,
            "available_tools": memory.available_tools,
        },
        "metadata": {
            "last_session_end": memory.last_session_end,
            "updated_at": memory.updated_at,
            "estimated_tokens": memory.estimate_tokens(),
        },
    }
    return format_response(result, format)


@mcp.tool()
def memory_add_discovery(
    content: str,
    importance: int = 2,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Add a discovery to memory.

    Discoveries are important findings that persist across sessions.
    Higher importance (1-5) means the discovery is kept longer during condensation.

    Args:
        content: What was discovered
        importance: 1-5, higher = more important (default 2)
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation.

    Examples:
        - "Found existing User model with is_active flag" (importance=3)
        - "Config uses pydantic-settings" (importance=2)
        - "DATABASE_URL required for tests" (importance=4)
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory_mgr.add_discovery(content, importance)

    return format_response({"success": True, "discovery": content, "importance": importance}, format)


@mcp.tool()
def memory_add_blocker(blocker: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Add a blocker to memory.

    Args:
        blocker: Blocker description
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory_mgr.add_blocker(blocker)

    return format_response({"success": True, "blocker": blocker}, format)


@mcp.tool()
def memory_resolve_blocker(blocker: str, path: Optional[str] = None, format: str = "toon") -> dict:
    """Mark a blocker as resolved.

    Args:
        blocker: Blocker to resolve
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory_mgr.remove_blocker(blocker)

    return format_response({"success": True, "resolved": blocker}, format)


@mcp.tool()
def memory_set_files(files: list[str], path: Optional[str] = None, format: str = "toon") -> dict:
    """Set the key files list in memory.

    Args:
        files: List of important file paths
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory_mgr.set_files(files)

    return format_response({"success": True, "files": files}, format)


@mcp.tool()
def memory_set_tools(tools: list[str], path: Optional[str] = None, format: str = "toon") -> dict:
    """Set the available tools list in memory.

    Args:
        tools: List of MCP tool names
        path: Directory to get context from (defaults to current directory)

    Returns:
        Confirmation.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    memory_mgr = MemoryManager(db, project_id)
    memory_mgr.set_tools(tools)

    return format_response({"success": True, "tools": tools}, format)


# --- Unified Tickets (v2) ---


@mcp.tool()
def unified_ticket_create(
    title: str,
    description: Optional[str] = None,
    acceptance_criteria: Optional[list[str]] = None,
    priority: int = 2,
    labels: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Create a unified ticket (local source).

    Unified tickets work with both local and external (Linear) sources.
    This creates a local ticket that can optionally be linked to Linear later.

    Args:
        title: Ticket title
        description: Optional description
        acceptance_criteria: Optional list of AC text
        priority: 0-4, higher = more important (default 2)
        labels: Optional labels
        tags: Optional local tags
        path: Directory to get context from (defaults to current directory)

    Returns:
        Created ticket.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_create(
        ticket_manager=ticket_mgr,
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        labels=labels,
        tags=tags,
    )
    return format_response(result, format)


@mcp.tool()
def unified_ticket_get(
    ticket_id: str,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Get a unified ticket by ID or external ID.

    Args:
        ticket_id: Ticket UUID or external ID (e.g., "SEM-45")
        path: Directory to get context from (defaults to current directory)

    Returns:
        Complete ticket information.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_get(ticket_mgr, ticket_id)
    return format_response(result, format)


@mcp.tool()
def unified_ticket_list(
    source: Optional[str] = None,
    status: Optional[str] = None,
    status_category: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """List unified tickets with optional filtering.

    Args:
        source: Filter by source (local, linear, jira)
        status: Filter by status
        status_category: Filter by normalized status (todo, in_progress, done, canceled)
        priority: Filter by priority (0-4)
        limit: Maximum results (default 20)
        offset: Skip first N
        path: Directory to get context from (defaults to current directory)

    Returns:
        List of ticket summaries.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_list(
        ticket_manager=ticket_mgr,
        source=source,
        status=status,
        status_category=status_category,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return format_response(result, format)


@mcp.tool()
def unified_ticket_update(
    ticket_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    status_category: Optional[str] = None,
    priority: Optional[int] = None,
    labels: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Update a unified ticket.

    Args:
        ticket_id: Ticket UUID
        title: New title
        description: New description
        status: New status
        status_category: New normalized status
        priority: New priority
        labels: New labels
        tags: New tags
        path: Directory to get context from (defaults to current directory)

    Returns:
        Updated ticket.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_update(
        ticket_manager=ticket_mgr,
        ticket_id=ticket_id,
        title=title,
        description=description,
        status=status,
        status_category=status_category,
        priority=priority,
        labels=labels,
        tags=tags,
    )
    return format_response(result, format)


@mcp.tool()
def unified_ticket_link_external(
    ticket_id: str,
    external_item_id: str,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Link a unified ticket to an external item.

    Args:
        ticket_id: Ticket UUID
        external_item_id: External item UUID (from external_items cache)
        path: Directory to get context from (defaults to current directory)

    Returns:
        Link status.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_link_external(ticket_mgr, ticket_id, external_item_id)
    return format_response(result, format)


@mcp.tool()
def unified_ticket_update_ac(
    ticket_id: str,
    ac_index: int,
    status: str,
    evidence: Optional[str] = None,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Update an acceptance criterion's status.

    Args:
        ticket_id: Ticket UUID
        ac_index: AC index (0-based)
        status: New status (pending, in_progress, verified, failed)
        evidence: Optional evidence of completion
        path: Directory to get context from (defaults to current directory)

    Returns:
        Update status.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_update_ac(ticket_mgr, ticket_id, ac_index, status, evidence)
    return format_response(result, format)


@mcp.tool()
def unified_ticket_add_ac(
    ticket_id: str,
    text: str,
    path: Optional[str] = None,
    format: str = "toon",
) -> dict:
    """Add an acceptance criterion to a ticket.

    Args:
        ticket_id: Ticket UUID
        text: AC text
        path: Directory to get context from (defaults to current directory)

    Returns:
        Index of the new AC.
    """
    try:
        db, project_id, context = _get_db_for_path(path)
    except Exception as e:
        return format_response({"error": "database_error", "message": str(e)}, format)

    ticket_mgr = TicketManager(db, project_id)
    result = svc_unified_ticket_add_ac(ticket_mgr, ticket_id, text)
    return format_response(result, format)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
