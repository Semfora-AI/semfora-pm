"""Main CLI for Semfora PM."""

import typer
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Optional

from .linear_client import LinearClient, LinearConfig, AuthenticationError
from .output import format_response, render_cli
from .services import resolve_context_info, scan_contexts
from .services.linear_tickets import (
    list_tickets as svc_list_tickets,
    get_ticket as svc_get_ticket,
    search_tickets as svc_search_tickets,
)
from .pm_config import (
    resolve_context,
    create_pm_config,
)
from .services.projects import (
    list_projects as svc_list_projects,
    list_labels as svc_list_labels,
    create_project as svc_create_project,
    add_tickets_to_project as svc_add_tickets_to_project,
    describe_project as svc_describe_project,
    show_project as svc_show_project,
)
from .services.labels import audit_labels as svc_audit_labels
from .services.links import link_blocks as svc_link_blocks, link_related as svc_link_related
from .services.sprints import (
    sprint_status as svc_sprint_status,
    sprint_status_aggregated as svc_sprint_status_aggregated,
    sprint_suggest as svc_sprint_suggest,
    sprint_plan as svc_sprint_plan,
)

app = typer.Typer(
    name="semfora-pm",
    help="Semfora Project Management - Linear integration for ticket management",
)
console = Console()

def get_client(path: Optional[Path] = None) -> LinearClient:
    """Get configured Linear client or exit with error.

    Args:
        path: Optional path for directory-based context detection
    """
    try:
        if path:
            return LinearClient.from_context(path)

        # Try context-based first
        context = resolve_context()
        if context.api_key and context.has_team():
            return LinearClient.from_context()

        # Fall back to legacy config
        config = LinearConfig.load()
        if not config:
            console.print("[red]Error:[/red] Linear API key not configured.")
            console.print("")
            console.print("To configure, use one of these methods:")
            console.print("")
            console.print("1. Create .pm/config.json in your project:")
            console.print("   [cyan]semfora-pm init[/cyan]")
            console.print("")
            console.print("2. Set environment variable:")
            console.print("   [cyan]export LINEAR_API_KEY=lin_api_xxx[/cyan]")
            console.print("")
            console.print("3. Run setup:")
            console.print("   [cyan]semfora-pm auth setup[/cyan]")
            raise typer.Exit(1)
        return LinearClient(config)
    except AuthenticationError as e:
        console.print(f"[red]Authentication Error:[/red] {e}")
        console.print("")
        console.print(LinearConfig.get_auth_help_message())
        raise typer.Exit(1)


# ============================================================================
# Context Commands
# ============================================================================


@app.command("context")
def show_context(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Path to check context for"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Show detected PM context for current or specified directory.

    Displays:
    - Config source (directory, parent, user, none)
    - Provider and team/project configuration
    - Authentication status
    """
    target_path = path or Path.cwd()
    data = resolve_context_info(target_path)
    response = format_response(data, output_format)
    console.print(render_cli(response))


@app.command("init")
def init_config(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Directory to initialize"),
    team_name: Optional[str] = typer.Option(None, "--team", "-t", help="Linear team name"),
    project_name: Optional[str] = typer.Option(None, "--project", help="Linear project name"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Environment variable for API key"),
):
    """Initialize .pm/config.json in current or specified directory.

    Creates a .pm/ folder with configuration for Linear integration.
    This enables directory-based context detection for multi-project workspaces.
    """
    target_path = Path(path) if path else Path.cwd()

    if not target_path.exists():
        console.print(f"[red]Error:[/red] Directory not found: {target_path}")
        raise typer.Exit(1)

    # Check if config already exists
    existing_config = target_path / ".pm" / "config.json"
    if existing_config.exists():
        if not typer.confirm(f"Config already exists at {existing_config}. Overwrite?"):
            raise typer.Exit(0)

    # If no team specified, try to get from auth
    if not team_name:
        try:
            config = LinearConfig.load()
            if config:
                client = LinearClient(config)
                teams = client.get_teams()
                if teams:
                    console.print("\nSelect a team:")
                    for i, team in enumerate(teams):
                        console.print(f"  [{i + 1}] {team['name']} ({team['key']})")
                    choice = typer.prompt("Enter number", type=int, default=1)
                    if 1 <= choice <= len(teams):
                        team_name = teams[choice - 1]["name"]
        except Exception:
            pass

    if not team_name:
        team_name = typer.prompt("Team name")

    # Get project name if not specified
    if not project_name:
        project_name = typer.prompt("Project name (optional, press Enter to skip)", default="")
        if not project_name:
            project_name = None

    # Create the config
    config_path = create_pm_config(
        path=target_path,
        team_name=team_name,
        project_name=project_name,
        api_key_env=api_key_env,
    )

    console.print(f"\n[green]Created:[/green] {config_path}")
    console.print("\n[dim]Config contents:[/dim]")
    console.print(config_path.read_text())
    console.print("\n[dim]Make sure LINEAR_API_KEY is set in your environment.[/dim]")


@app.command("scan")
def scan_directories(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Base directory to scan"),
    max_depth: int = typer.Option(3, "--depth", "-d", help="Maximum depth to scan"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Scan directory tree for .pm/ configurations.

    Useful for discovering all PM-configured projects in a workspace.
    """
    target_path = Path(path) if path else Path.cwd()
    results = scan_contexts(target_path, max_depth)
    payload = {
        "base_path": str(target_path),
        "count": len(results),
        "directories": results,
    }
    response = format_response(payload, output_format)
    console.print(render_cli(response))


# ============================================================================
# Auth Commands
# ============================================================================

auth_app = typer.Typer(help="Authentication commands")
app.add_typer(auth_app, name="auth")


@auth_app.command("setup")
def auth_setup(
    api_key: str = typer.Option(..., prompt=True, hide_input=True, help="Linear API key"),
):
    """Configure Linear API authentication."""
    config = LinearConfig(api_key=api_key)

    # Test the connection
    try:
        client = LinearClient(config)
        teams = client.get_teams()

        if not teams:
            console.print("[red]Error:[/red] No teams found. Check your API key permissions.")
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] Connected successfully! Found {len(teams)} team(s):")
        for team in teams:
            console.print(f"  • {team['name']} ({team['key']})")

        # Ask which team to use by default
        if len(teams) == 1:
            config.team_id = teams[0]["id"]
            console.print(f"\n[dim]Using team: {teams[0]['name']}[/dim]")
        else:
            console.print("\nSelect default team:")
            for i, team in enumerate(teams):
                console.print(f"  [{i+1}] {team['name']}")
            choice = typer.prompt("Enter number", type=int, default=1)
            config.team_id = teams[choice - 1]["id"]

        config.save()
        console.print("\n[green]✓[/green] Configuration saved!")

    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to connect: {e}")
        raise typer.Exit(1)


@auth_app.command("status")
def auth_status():
    """Check authentication status."""
    config = LinearConfig.load()
    if not config:
        console.print("[red]✗[/red] Not authenticated")
        console.print("Run: [cyan]semfora-pm auth setup[/cyan]")
        raise typer.Exit(1)

    try:
        client = LinearClient(config)
        teams = client.get_teams()
        console.print("[green]✓[/green] Authenticated")
        console.print(f"  Teams: {', '.join(t['name'] for t in teams)}")
        if config.team_id:
            team_name = next((t["name"] for t in teams if t["id"] == config.team_id), "Unknown")
            console.print(f"  Default team: {team_name}")
    except Exception as e:
        console.print(f"[red]✗[/red] Authentication failed: {e}")
        raise typer.Exit(1)


# ============================================================================
# Ticket Commands
# ============================================================================

@app.command("list")
def list_tickets(
    state: Optional[str] = typer.Option(None, "-s", "--state", help="Filter by state (e.g., Backlog, Todo, 'In Progress')"),
    label: Optional[str] = typer.Option(None, "-l", "--label", help="Filter by label"),
    priority: Optional[int] = typer.Option(None, "-p", "--priority", help="Filter by priority (1=Urgent, 2=High, 3=Medium, 4=Low)"),
    limit: int = typer.Option(50, "--limit", help="Maximum tickets to show"),
    sprint: bool = typer.Option(False, "--sprint", help="Show only current sprint tickets (Todo/In Progress/In Review)"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    offset: int = typer.Option(0, "--offset", help="Skip first N tickets for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """List tickets from Linear with rich details.

    Shows ticket ID, title, state, priority, estimate, labels, and a short description.
    """
    result = svc_list_tickets(
        path=path,
        state=state,
        label=label,
        priority=priority,
        sprint_only=sprint,
        limit=limit,
        offset=offset,
    )
    response = format_response(result, output_format)
    console.print(render_cli(response))


@app.command("show")
def show_ticket(
    identifier: str = typer.Argument(..., help="Linear ticket identifier (e.g., SEM-123)"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Show full ticket details from Linear.

    Displays all available information for a ticket including full description,
    labels, assignee, dates, and related data.
    """
    result = svc_get_ticket(identifier, path=path)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@app.command("get-ticket")
def get_ticket_json(
    identifier: str = typer.Argument(..., help="Linear ticket identifier (e.g., SEM-123)"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Get ticket details as JSON (for programmatic use by AI agents)."""
    result = svc_get_ticket(identifier, path=path)
    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Project Commands
# ============================================================================

project_app = typer.Typer(help="Linear project commands")
app.add_typer(project_app, name="project")


@project_app.command("list")
def project_list(
    limit: int = typer.Option(50, "--limit", help="Maximum projects to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N projects for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """List Linear projects."""
    result = svc_list_projects(limit=limit, offset=offset)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@project_app.command("labels")
def project_labels(
    limit: int = typer.Option(200, "--limit", help="Maximum labels to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N labels for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """List available labels."""
    result = svc_list_labels(limit=limit, offset=offset)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: Optional[str] = typer.Option(None, "-d", "--description", help="Project description"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Create a new Linear project."""
    result = svc_create_project(name=name, description=description)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@project_app.command("add")
def project_add(
    project_name: str = typer.Argument(..., help="Project name"),
    tickets: Optional[str] = typer.Option(None, "-t", "--tickets", help="Comma-separated ticket IDs or Linear identifiers"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Add tickets to a Linear project."""
    if not tickets:
        console.print("[yellow]Provide --tickets with Linear identifiers to add.[/yellow]")
        raise typer.Exit(0)

    ticket_ids = [t.strip() for t in tickets.split(",") if t.strip()]
    result = svc_add_tickets_to_project(project_name, ticket_ids)
    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Link Commands
# ============================================================================

link_app = typer.Typer(help="Manage issue relationships")
app.add_typer(link_app, name="link")


@link_app.command("blocks")
def link_blocks(
    blocker: str = typer.Argument(..., help="Issue that blocks (e.g., SEM-5 or engine-001)"),
    blocked: str = typer.Argument(..., help="Issue that is blocked (e.g., SEM-6 or adk-001)"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Create a 'blocks' relationship between issues."""
    result = svc_link_blocks(blocker, blocked)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@link_app.command("related")
def link_related(
    issue1: str = typer.Argument(..., help="First issue (e.g., SEM-5)"),
    issue2: str = typer.Argument(..., help="Second issue (e.g., SEM-6)"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Create a 'related' relationship between issues."""
    result = svc_link_related(issue1, issue2)
    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Labels Commands
# ============================================================================

labels_app = typer.Typer(help="Label management commands")
app.add_typer(labels_app, name="labels")



@labels_app.command("audit")
def labels_audit(
    apply: bool = typer.Option(False, "--apply", help="Apply color changes"),
    show_invalid: bool = typer.Option(False, "--show-invalid", help="Show comma-separated labels"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Audit labels and assign colors based on category.

    Scans all labels, identifies their category, and assigns appropriate colors.
    Comma-separated labels (improperly imported) are skipped but can be shown.
    """
    result = svc_audit_labels(apply=apply, show_invalid=show_invalid)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@labels_app.command("list")
def labels_list(
    limit: int = typer.Option(200, "--limit", help="Maximum labels to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N labels for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """List all labels with their colors."""
    result = svc_list_labels(limit=limit, offset=offset)
    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Sprint Commands
# ============================================================================

sprint_app = typer.Typer(help="Sprint planning and management")
app.add_typer(sprint_app, name="sprint")


@sprint_app.command("plan")
def sprint_plan(
    name: str = typer.Argument(..., help="Sprint name (e.g., 'sprint-1')"),
    tickets: str = typer.Option(..., "-t", "--tickets", help="Comma-separated Linear identifiers (e.g., SEM-32,SEM-33)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan without making changes"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Plan a sprint by moving tickets from Backlog to Todo.

    Use Linear identifiers (e.g., SEM-32, SEM-33) directly.
    """
    ticket_ids = [t.strip() for t in tickets.split(",") if t.strip()]
    result = svc_sprint_plan(name=name, tickets=ticket_ids, dry_run=dry_run, path=path)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@sprint_app.command("suggest")
def sprint_suggest(
    points: int = typer.Option(20, "-p", "--points", help="Target story points for sprint"),
    label: Optional[str] = typer.Option(None, "-l", "--label", help="Filter by label"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    limit: int = typer.Option(20, "--limit", help="Maximum suggestions to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N suggestions for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Suggest tickets for next sprint based on priority.

    Queries Linear backlog and suggests tickets that fit the point budget.
    """
    result = svc_sprint_suggest(points=points, label=label, limit=limit, offset=offset, path=path)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@sprint_app.command("status")
def sprint_status(
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    aggregate: bool = typer.Option(False, "--aggregate", "-a", help="Aggregate across all .pm/ configs in directory tree"),
    limit: int = typer.Option(20, "--limit", help="Maximum tickets per group"),
    offset: int = typer.Option(0, "--offset", help="Skip first N tickets per group"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Show current sprint status (tickets in Todo/In Progress).

    Use --aggregate to scan for all .pm/ configs and show combined sprint status
    across all configured teams/projects (deduping when they share the same project).
    """
    if aggregate:
        result = svc_sprint_status_aggregated(base_path=path, limit=limit, offset=offset)
    else:
        result = svc_sprint_status(path=path, limit=limit, offset=offset)

    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Project Description Command
# ============================================================================

@project_app.command("describe")
def project_describe(
    project_name: str = typer.Argument(..., help="Project name"),
    description: str = typer.Option(..., "-d", "--description", help="Project description"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Update a project's description."""
    result = svc_describe_project(project_name, description)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@project_app.command("show")
def project_show(
    project_name: str = typer.Argument(..., help="Project name"),
    limit: int = typer.Option(50, "--limit", help="Maximum issues to show"),
    offset: int = typer.Option(0, "--offset", help="Skip first N issues for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Show project details including tickets."""
    result = svc_show_project(project_name, limit=limit, offset=offset)
    response = format_response(result, output_format)
    console.print(render_cli(response))


# ============================================================================
# Tickets Commands (Bulk Creation for AI Agents)
# ============================================================================

tickets_app = typer.Typer(help="Ticket creation and search (optimized for AI agents)")
app.add_typer(tickets_app, name="tickets")


@tickets_app.command("search")
def tickets_search(
    query: str = typer.Argument(..., help="Search query for ticket titles"),
    limit: int = typer.Option(20, "--limit", help="Maximum results"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
    offset: int = typer.Option(0, "--offset", help="Skip first N tickets for pagination"),
    output_format: str = typer.Option("toon", "--format", "-f", help="Output format (toon|json|text)"),
):
    """Search for existing tickets by title.

    Use this BEFORE creating tickets to check for duplicates.
    This is especially important for AI agents planning features.
    """
    result = svc_search_tickets(query, path=path, limit=limit, offset=offset)
    response = format_response(result, output_format)
    console.print(render_cli(response))


@tickets_app.command("update")
def tickets_update(
    identifier: str = typer.Argument(..., help="Linear ticket identifier (e.g., SEM-123)"),
    state: Optional[str] = typer.Option(None, "-s", "--state", help="New state (Backlog, Todo, 'In Progress', 'In Review', Done, Canceled)"),
    priority: Optional[int] = typer.Option(None, "-p", "--priority", help="New priority (1=Urgent, 2=High, 3=Medium, 4=Low)"),
    estimate: Optional[int] = typer.Option(None, "-e", "--estimate", help="Story point estimate"),
    add_labels: Optional[str] = typer.Option(None, "--add-labels", help="Comma-separated labels to add"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description (use @filename to read from file)"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
):
    """Update a ticket's status, priority, or other fields.

    Common state transitions for AI agents:

    \b
    - Start work:    semfora-pm tickets update SEM-123 -s "In Progress"
    - Submit review: semfora-pm tickets update SEM-123 -s "In Review"
    - Complete:      semfora-pm tickets update SEM-123 -s Done
    - Back to todo:  semfora-pm tickets update SEM-123 -s Todo
    - Block/defer:   semfora-pm tickets update SEM-123 -s Backlog

    Examples:

    \b
    # Update state
    semfora-pm tickets update SEM-45 --state "In Progress"

    \b
    # Update multiple fields
    semfora-pm tickets update SEM-45 -s Done -p 2 -e 5

    \b
    # Add labels
    semfora-pm tickets update SEM-45 --add-labels "bug,urgent"
    """
    client = get_client(path)

    # Get team_id from context or legacy config
    context = resolve_context(path)
    team_id = context.team_id
    if not team_id and context.team_name:
        team_id = client.get_team_id_by_name(context.team_name)

    if not team_id:
        config = LinearConfig.load()
        team_id = config.team_id if config else None

    if not team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Check if any update was requested
    if not any([state, priority, estimate, add_labels, title, description]):
        console.print("[yellow]No updates specified.[/yellow]")
        console.print("Use --state, --priority, --estimate, --add-labels, --title, or --description")
        raise typer.Exit(1)

    # Get current issue to show before/after
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching {identifier}...", total=None)
        issue = client.get_issue_by_identifier(identifier)

    if not issue:
        console.print(f"[red]Error:[/red] Ticket not found: {identifier}")
        raise typer.Exit(1)

    # Prepare update arguments
    update_args: dict = {}
    changes: list[str] = []

    # Handle state change
    state_id = None
    if state:
        states = client.get_team_states(team_id)
        # Try exact match first, then case-insensitive
        state_id = states.get(state)
        if not state_id:
            for name, sid in states.items():
                if name.lower() == state.lower():
                    state_id = sid
                    state = name  # Use correct casing
                    break

        if not state_id:
            console.print(f"[red]Error:[/red] Unknown state '{state}'")
            console.print(f"Valid states: {', '.join(states.keys())}")
            raise typer.Exit(1)

        update_args["state_id"] = state_id
        changes.append(f"State: {issue['state']['name']} → [cyan]{state}[/cyan]")

    # Handle priority
    if priority is not None:
        if priority not in [0, 1, 2, 3, 4]:
            console.print("[red]Error:[/red] Priority must be 0-4 (1=Urgent, 2=High, 3=Medium, 4=Low, 0=None)")
            raise typer.Exit(1)
        update_args["priority"] = priority
        priority_map = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
        old_pri = priority_map.get(issue.get("priority", 0), "?")
        new_pri = priority_map.get(priority, "?")
        changes.append(f"Priority: {old_pri} → [cyan]{new_pri}[/cyan]")

    # Handle estimate
    if estimate is not None:
        update_args["estimate"] = estimate
        old_est = issue.get("estimate") or "—"
        changes.append(f"Estimate: {old_est} → [cyan]{estimate}[/cyan]")

    # Handle labels (add to existing)
    if add_labels:
        new_labels = [l.strip() for l in add_labels.split(",") if l.strip()]
        existing_labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
        all_labels = list(set(existing_labels + new_labels))
        update_args["labels"] = all_labels
        changes.append(f"Labels: +[cyan]{', '.join(new_labels)}[/cyan]")

    # Handle title
    if title:
        update_args["title"] = title
        changes.append(f"Title: [cyan]{title[:40]}...[/cyan]" if len(title) > 40 else f"Title: [cyan]{title}[/cyan]")

    # Handle description
    if description:
        # Support @filename syntax
        if description.startswith("@"):
            filepath = Path(description[1:])
            if not filepath.exists():
                console.print(f"[red]Error:[/red] File not found: {filepath}")
                raise typer.Exit(1)
            description = filepath.read_text()
        update_args["description"] = description
        changes.append(f"Description: [cyan](updated)[/cyan]")

    # Show what will change
    console.print(f"\n[bold]Updating {identifier}:[/bold] {issue['title'][:50]}")
    for change in changes:
        console.print(f"  {change}")

    # Perform update
    try:
        client.update_issue(issue["id"], **update_args)
        console.print(f"\n[green]✓[/green] Updated {identifier}")
    except Exception as e:
        console.print(f"\n[red]✗[/red] Failed to update: {e}")
        raise typer.Exit(1)


@tickets_app.command("create")
def tickets_create(
    file: Path = typer.Argument(..., help="JSON file with ticket definitions"),
    skip_duplicates: bool = typer.Option(False, "--skip-duplicates", help="Skip duplicate check"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be created without creating"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompts"),
    path: Optional[Path] = typer.Option(None, "--path", help="Path for context detection"),
):
    """Create multiple tickets with relationships from a JSON file.

    This command is designed for AI agents planning features. It:
    1. Checks for potential duplicates (unless --skip-duplicates)
    2. Creates all tickets in dependency order
    3. Sets up relationships (blocks, blocked_by, related)
    4. Optionally adds to project/milestone and sprint

    Example JSON format:

    \b
    {
      "project": "My Project",
      "milestone": "v1.0",
      "sprint": true,
      "tickets": [
        {
          "id": "main-feature",
          "title": "Main feature",
          "description": "Description here",
          "priority": 2,
          "estimate": 5,
          "labels": ["feature", "core"]
        },
        {
          "id": "subtask-1",
          "title": "Subtask 1",
          "blocked_by": ["main-feature"],
          "priority": 3,
          "estimate": 3
        },
        {
          "id": "subtask-2",
          "title": "Subtask 2",
          "blocked_by": ["subtask-1"],
          "related": ["main-feature"]
        }
      ]
    }
    """
    import json

    client = get_client(path)

    # Get team_id from context or legacy config
    context = resolve_context(path)
    team_id = context.team_id
    if not team_id and context.team_name:
        team_id = client.get_team_id_by_name(context.team_name)

    if not team_id:
        config = LinearConfig.load()
        team_id = config.team_id if config else None

    if not team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Load the file
    if not file.exists():
        console.print(f"[red]Error:[/red] File not found: {file}")
        raise typer.Exit(1)

    content = file.read_text()
    try:
        if file.suffix != ".json":
            console.print("[red]Error:[/red] Only JSON input is supported.")
            raise typer.Exit(1)
        data = json.loads(content)
    except Exception as e:
        console.print(f"[red]Error parsing file:[/red] {e}")
        raise typer.Exit(1)

    tickets_data = data.get("tickets", [])
    if not tickets_data:
        console.print("[red]Error:[/red] No tickets defined in file")
        raise typer.Exit(1)

    # Validate ticket structure
    temp_ids = set()
    for ticket in tickets_data:
        if "id" not in ticket:
            console.print(f"[red]Error:[/red] Ticket missing 'id' field: {ticket.get('title', 'unknown')}")
            raise typer.Exit(1)
        if "title" not in ticket:
            console.print(f"[red]Error:[/red] Ticket missing 'title' field: {ticket['id']}")
            raise typer.Exit(1)
        if ticket["id"] in temp_ids:
            console.print(f"[red]Error:[/red] Duplicate ticket id: {ticket['id']}")
            raise typer.Exit(1)
        temp_ids.add(ticket["id"])

    # Collect all external Linear IDs referenced (e.g., SEM-14, PROJ-123)
    external_refs = set()
    for ticket in tickets_data:
        for ref in ticket.get("blocked_by", []) + ticket.get("blocks", []) + ticket.get("related", []):
            if ref not in temp_ids:
                # Check if it looks like a Linear ID (e.g., SEM-14, PROJ-123)
                if "-" in ref and ref.split("-")[0].isupper() and ref.split("-")[-1].isdigit():
                    external_refs.add(ref)
                else:
                    console.print(f"[red]Error:[/red] Unknown reference '{ref}' in ticket '{ticket['id']}'")
                    console.print(f"[dim]Hint: Use Linear IDs (e.g., SEM-14) for existing tickets or temp IDs defined in this file[/dim]")
                    raise typer.Exit(1)

    # Look up external Linear IDs to get their UUIDs
    external_id_mapping: dict[str, dict] = {}  # Linear ID -> {id: uuid, identifier: SEM-XX}
    if external_refs:
        console.print(f"\n[dim]Looking up {len(external_refs)} existing ticket(s)...[/dim]")
        for linear_id in external_refs:
            try:
                issue = client.get_issue_by_identifier(linear_id)
                if issue:
                    external_id_mapping[linear_id] = {
                        "id": issue["id"],
                        "identifier": issue["identifier"],
                        "title": issue.get("title", ""),
                    }
                    console.print(f"  [green]✓[/green] Found {linear_id}: {issue.get('title', '')[:40]}")
                else:
                    console.print(f"[red]Error:[/red] Could not find Linear ticket '{linear_id}'")
                    raise typer.Exit(1)
            except Exception as e:
                console.print(f"[red]Error:[/red] Failed to look up '{linear_id}': {e}")
                raise typer.Exit(1)

    # Check for circular dependencies in blocked_by
    def find_cycle(ticket_id: str, visited: set, path: list) -> Optional[list]:
        if ticket_id in path:
            return path[path.index(ticket_id):] + [ticket_id]
        if ticket_id in visited:
            return None
        visited.add(ticket_id)
        path.append(ticket_id)
        ticket = next((t for t in tickets_data if t["id"] == ticket_id), None)
        if ticket:
            for dep in ticket.get("blocked_by", []):
                cycle = find_cycle(dep, visited, path.copy())
                if cycle:
                    return cycle
        return None

    for ticket in tickets_data:
        cycle = find_cycle(ticket["id"], set(), [])
        if cycle:
            console.print(f"[red]Error:[/red] Circular dependency detected: {' -> '.join(cycle)}")
            raise typer.Exit(1)

    console.print(f"\n[bold]Ticket Creation Plan[/bold]")
    console.print(f"  Tickets to create: {len(tickets_data)}")
    if data.get("project"):
        console.print(f"  Project: {data['project']}")
    if data.get("milestone"):
        console.print(f"  Milestone: {data['milestone']}")
    if data.get("sprint"):
        console.print(f"  Add to sprint: Yes (move to Todo)")

    # === DUPLICATE CHECK ===
    if not skip_duplicates:
        console.print(f"\n[bold]=== Duplicate Check ===[/bold]")
        titles = [t["title"] for t in tickets_data]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task("Searching for similar tickets...", total=None)
            similar = client.search_issues_multi(titles, team_id)

        if similar:
            console.print(f"\n[yellow]⚠️  Found {len(similar)} potentially similar existing tickets:[/yellow]\n")
            for issue in similar[:15]:
                state = issue["state"]["name"]
                console.print(f"  [cyan]{issue['identifier']}[/]: {issue['title'][:55]}")
                console.print(f"      [dim]State: {state}[/dim]")

            if len(similar) > 15:
                console.print(f"  [dim]...and {len(similar) - 15} more[/dim]")

            console.print(f"\n[bold yellow]IMPORTANT: Review these tickets before proceeding![/bold yellow]")
            console.print("[dim]Run 'semfora-pm list' or 'semfora-pm show <ID>' for details.[/dim]\n")

            if not yes and not dry_run:
                if not typer.confirm("Continue with ticket creation?", default=False):
                    console.print("[dim]Aborted.[/dim]")
                    raise typer.Exit(0)
        else:
            console.print("[green]No similar tickets found.[/green]")

    # === SHOW PLAN ===
    console.print(f"\n[bold]=== Tickets to Create ===[/bold]\n")

    # Topologically sort tickets (blockers first)
    def topo_sort(tickets: list) -> list:
        """Sort tickets so blockers come before blocked tickets."""
        result = []
        remaining = tickets.copy()
        ids_created = set()

        while remaining:
            # Find tickets whose dependencies are all satisfied
            ready = []
            for t in remaining:
                deps = set(t.get("blocked_by", []))
                if deps <= ids_created:
                    ready.append(t)

            if not ready:
                # No progress - remaining tickets have unsatisfied deps (shouldn't happen after cycle check)
                ready = remaining[:1]

            for t in ready:
                result.append(t)
                ids_created.add(t["id"])
                remaining.remove(t)

        return result

    sorted_tickets = topo_sort(tickets_data)

    priority_map = {1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
    for ticket in sorted_tickets:
        pri = priority_map.get(ticket.get("priority", 3), "Medium")
        est = ticket.get("estimate", "—")
        labels = ", ".join(ticket.get("labels", [])) or "—"
        blocked_by = ", ".join(ticket.get("blocked_by", [])) or "—"

        console.print(f"  [cyan]{ticket['id']}[/]: {ticket['title'][:50]}")
        console.print(f"      Priority: {pri} | Estimate: {est} | Labels: {labels}")
        if blocked_by != "—":
            console.print(f"      [dim]Blocked by: {blocked_by}[/dim]")

    if dry_run:
        console.print(f"\n[yellow]Dry run - no tickets created[/yellow]")
        raise typer.Exit(0)

    if not yes:
        if not typer.confirm(f"\nCreate {len(sorted_tickets)} tickets?"):
            raise typer.Exit(0)

    # === CREATE TICKETS ===
    console.print(f"\n[bold]=== Creating Tickets ===[/bold]\n")

    # Get project ID if specified
    project_id = None
    if data.get("project"):
        projects = client.get_projects(team_id)
        project = next((p for p in projects if p["name"].lower() == data["project"].lower()), None)
        if project:
            project_id = project["id"]
        else:
            console.print(f"[yellow]Warning: Project '{data['project']}' not found[/yellow]")

    # Get milestone ID if specified
    milestone_id = None
    if data.get("milestone") and project_id:
        milestones = client.get_project_milestones(project_id)
        milestone = next((m for m in milestones if m["name"].lower() == data["milestone"].lower()), None)
        if milestone:
            milestone_id = milestone["id"]
        else:
            console.print(f"[yellow]Warning: Milestone '{data['milestone']}' not found[/yellow]")

    # Get Todo state ID for sprint
    todo_state_id = None
    if data.get("sprint"):
        states = client.get_team_states(team_id)
        todo_state_id = states.get("Todo")

    # Create tickets and track temp_id -> linear_id mapping
    id_mapping: dict[str, dict] = {}  # temp_id -> {id: linear_id, identifier: SEM-XX}
    created_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Creating tickets...", total=len(sorted_tickets))

        for ticket in sorted_tickets:
            try:
                issue = client.create_issue(
                    title=ticket["title"],
                    description=ticket.get("description", ""),
                    team_id=team_id,
                    priority=ticket.get("priority", 3),
                    labels=ticket.get("labels"),
                    estimate=ticket.get("estimate"),
                    state_id=todo_state_id,
                    project_id=project_id,
                    milestone_id=milestone_id,
                )

                id_mapping[ticket["id"]] = {
                    "id": issue["id"],
                    "identifier": issue["identifier"],
                    "title": ticket["title"],
                }
                created_count += 1
                progress.console.print(f"  [green]✓[/green] {ticket['id']} -> [cyan]{issue['identifier']}[/]: {ticket['title'][:40]}")

            except Exception as e:
                progress.console.print(f"  [red]✗[/red] {ticket['id']}: {e}")

            progress.advance(task)

    # === CREATE RELATIONSHIPS ===
    # Merge id_mapping with external_id_mapping for relationship lookups
    all_id_mapping = {**id_mapping, **external_id_mapping}

    relations_to_create = []
    for ticket in tickets_data:
        if ticket["id"] not in id_mapping:
            continue

        linear_id = id_mapping[ticket["id"]]["id"]

        # blocked_by -> the other ticket blocks this one
        for blocker_ref in ticket.get("blocked_by", []):
            if blocker_ref in all_id_mapping:
                relations_to_create.append({
                    "from": all_id_mapping[blocker_ref],
                    "to": id_mapping[ticket["id"]],
                    "type": "blocks",
                    "desc": f"{all_id_mapping[blocker_ref]['identifier']} blocks {id_mapping[ticket['id']]['identifier']}",
                })

        # blocks -> this ticket blocks the other
        for blocked_ref in ticket.get("blocks", []):
            if blocked_ref in all_id_mapping:
                relations_to_create.append({
                    "from": id_mapping[ticket["id"]],
                    "to": all_id_mapping[blocked_ref],
                    "type": "blocks",
                    "desc": f"{id_mapping[ticket['id']]['identifier']} blocks {all_id_mapping[blocked_ref]['identifier']}",
                })

        # related
        for related_ref in ticket.get("related", []):
            if related_ref in all_id_mapping:
                # Get identifiers for dedup check
                this_identifier = id_mapping[ticket["id"]]["identifier"]
                related_identifier = all_id_mapping[related_ref]["identifier"]

                # Avoid duplicate relations (A related B == B related A)
                pair = tuple(sorted([this_identifier, related_identifier]))
                if not any(
                    r["type"] == "related" and tuple(sorted([r["from"]["identifier"], r["to"]["identifier"]])) == pair
                    for r in relations_to_create
                ):
                    relations_to_create.append({
                        "from": id_mapping[ticket["id"]],
                        "to": all_id_mapping[related_ref],
                        "type": "related",
                        "desc": f"{this_identifier} <-> {related_identifier} (related)",
                    })

    if relations_to_create:
        console.print(f"\n[bold]=== Creating Relationships ===[/bold]\n")

        relation_count = 0
        for rel in relations_to_create:
            try:
                client.create_issue_relation(
                    rel["from"]["id"],
                    rel["to"]["id"],
                    rel["type"],
                )
                console.print(f"  [green]✓[/green] {rel['desc']}")
                relation_count += 1
            except Exception as e:
                console.print(f"  [red]✗[/red] {rel['desc']}: {e}")

    # === SUMMARY ===
    console.print(f"\n[bold]=== Summary ===[/bold]\n")
    console.print(f"[green]Created {created_count}/{len(sorted_tickets)} tickets:[/green]")

    for temp_id, info in id_mapping.items():
        console.print(f"  [cyan]{info['identifier']}[/]: {info['title'][:50]}")

    if project_id:
        console.print(f"\n  Project: {data['project']}")
    if milestone_id:
        console.print(f"  Milestone: {data['milestone']}")
    if todo_state_id:
        console.print(f"  Sprint: Added to Todo")

    if relations_to_create:
        console.print(f"\n  Relationships created: {relation_count}")

    # Final warning about duplicates
    console.print(f"\n[bold yellow]{'═' * 60}[/bold yellow]")
    console.print(f"[bold yellow]⚠️  IMPORTANT: Review created tickets for duplicates![/bold yellow]")
    console.print(f"[bold yellow]{'═' * 60}[/bold yellow]")
    console.print(f"\nRun: [cyan]semfora-pm list --limit 50[/cyan]")
    console.print(f"Or:  [cyan]semfora-pm show {list(id_mapping.values())[0]['identifier'] if id_mapping else 'SEM-XX'}[/cyan]")


if __name__ == "__main__":
    app()
