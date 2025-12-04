"""Main CLI for Semfora PM."""

import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Optional

from .linear_client import LinearClient, LinearConfig
from .models.ticket import Ticket, load_tickets, save_tickets, Component

app = typer.Typer(
    name="semfora-pm",
    help="Semfora Project Management - Linear integration for ticket management",
)
console = Console()

# Default paths
TICKETS_DIR = Path(__file__).parent.parent.parent.parent / "tickets"


def get_client() -> LinearClient:
    """Get configured Linear client or exit with error."""
    config = LinearConfig.load()
    if not config:
        console.print("[red]Error:[/red] Linear API key not configured.")
        console.print("Run: [cyan]semfora-pm auth setup[/cyan]")
        raise typer.Exit(1)
    return LinearClient(config)


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
):
    """List tickets from Linear with rich details.

    Shows ticket ID, title, state, priority, estimate, labels, and a short description.
    """
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        console.print("Run: [cyan]semfora-pm auth setup[/cyan]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("Fetching tickets from Linear...", total=None)
        issues = client.get_team_issues(config.team_id, limit=limit * 2)  # Fetch extra for filtering

    # Apply filters
    if sprint:
        sprint_states = {"Todo", "In Progress", "In Review"}
        issues = [i for i in issues if i["state"]["name"] in sprint_states]
    elif state:
        issues = [i for i in issues if i["state"]["name"].lower() == state.lower()]

    if label:
        issues = [
            i for i in issues
            if any(l["name"].lower() == label.lower() for l in i.get("labels", {}).get("nodes", []))
        ]

    if priority is not None:
        issues = [i for i in issues if i.get("priority") == priority]

    # Limit results
    issues = issues[:limit]

    if not issues:
        console.print("[yellow]No tickets found matching filters.[/yellow]")
        raise typer.Exit(0)

    # Priority mapping
    priority_map = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
    priority_colors = {0: "dim", 1: "red", 2: "yellow", 3: "blue", 4: "dim"}

    table = Table(title="Linear Tickets")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white", max_width=45)
    table.add_column("State", style="magenta", no_wrap=True)
    table.add_column("Priority", no_wrap=True)
    table.add_column("Est", style="blue", justify="center", no_wrap=True)
    table.add_column("Labels", style="dim", max_width=30)
    table.add_column("Description", style="dim", max_width=40)

    for issue in issues:
        # Format priority with color
        pri = issue.get("priority", 0)
        pri_str = f"[{priority_colors.get(pri, 'white')}]{priority_map.get(pri, str(pri))}[/]"

        # Format labels (first 3)
        labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])][:3]
        labels_str = ", ".join(labels) if labels else "—"

        # Format estimate
        estimate = issue.get("estimate")
        est_str = str(estimate) if estimate else "—"

        # Short description (first 60 chars, first line only)
        desc = issue.get("description") or ""
        desc_short = desc.split("\n")[0][:60]
        if len(desc) > 60 or "\n" in desc:
            desc_short += "..."

        # Title (truncate if needed)
        title = issue["title"]
        if len(title) > 45:
            title = title[:42] + "..."

        table.add_row(
            issue["identifier"],
            title,
            issue["state"]["name"],
            pri_str,
            est_str,
            labels_str,
            desc_short or "—",
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(issues)} tickets[/dim]")

    # Show filter hints
    if not any([state, label, priority, sprint]):
        console.print("[dim]Use --sprint to show active sprint tickets, or -s/--state to filter by state[/dim]")


@app.command("show")
def show_ticket(
    identifier: str = typer.Argument(..., help="Linear ticket identifier (e.g., SEM-123)"),
):
    """Show full ticket details from Linear.

    Displays all available information for a ticket including full description,
    labels, assignee, dates, and related data.
    """
    client = get_client()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Fetching {identifier}...", total=None)
        issue = client.get_issue_full(identifier)

    if not issue:
        console.print(f"[red]Ticket not found:[/red] {identifier}")
        raise typer.Exit(1)

    # Priority mapping
    priority_map = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
    pri = issue.get("priority", 0)
    pri_str = priority_map.get(pri, str(pri))

    # Format labels
    labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
    labels_str = ", ".join(labels) if labels else "—"

    # Format assignee
    assignee = issue.get("assignee")
    assignee_str = assignee["name"] if assignee else "Unassigned"

    # Format dates
    created = issue.get("createdAt", "")[:10] if issue.get("createdAt") else "—"
    updated = issue.get("updatedAt", "")[:10] if issue.get("updatedAt") else "—"

    # Format project
    project = issue.get("project")
    project_str = project["name"] if project else "—"

    # Format cycle
    cycle = issue.get("cycle")
    cycle_str = cycle["name"] if cycle else "—"

    # Format parent issue
    parent = issue.get("parent")
    parent_str = f"{parent['identifier']}: {parent['title'][:30]}" if parent else "—"

    # Format sub-issues
    sub_issues = issue.get("children", {}).get("nodes", [])
    sub_issues_str = ""
    if sub_issues:
        sub_issues_str = "\n".join(f"  • {s['identifier']}: {s['title'][:40]}" for s in sub_issues[:5])
        if len(sub_issues) > 5:
            sub_issues_str += f"\n  [dim]...and {len(sub_issues) - 5} more[/dim]"

    # Format relations
    relations = issue.get("relations", {}).get("nodes", [])
    blocks = [r for r in relations if r.get("type") == "blocks"]
    blocked_by = [r for r in relations if r.get("type") == "blocked"]
    related = [r for r in relations if r.get("type") == "related"]

    def format_relations(rels: list) -> str:
        if not rels:
            return "—"
        items = []
        for r in rels[:3]:
            related_issue = r.get("relatedIssue", {})
            items.append(f"{related_issue.get('identifier', '?')}: {related_issue.get('title', '')[:30]}")
        return "\n  ".join(items)

    panel_content = f"""[bold]{issue['title']}[/bold]

[cyan]State:[/cyan] {issue['state']['name']}
[cyan]Priority:[/cyan] {pri_str}
[cyan]Estimate:[/cyan] {issue.get('estimate') or '—'} points
[cyan]Assignee:[/cyan] {assignee_str}
[cyan]Labels:[/cyan] {labels_str}

[cyan]Project:[/cyan] {project_str}
[cyan]Cycle:[/cyan] {cycle_str}
[cyan]Parent:[/cyan] {parent_str}

[cyan]Created:[/cyan] {created}
[cyan]Updated:[/cyan] {updated}

[cyan]URL:[/cyan] {issue.get('url', '—')}
"""

    if sub_issues_str:
        panel_content += f"\n[cyan]Sub-issues:[/cyan]\n{sub_issues_str}\n"

    if blocks:
        panel_content += f"\n[cyan]Blocks:[/cyan]\n  {format_relations(blocks)}\n"
    if blocked_by:
        panel_content += f"\n[cyan]Blocked by:[/cyan]\n  {format_relations(blocked_by)}\n"
    if related:
        panel_content += f"\n[cyan]Related:[/cyan]\n  {format_relations(related)}\n"

    # Description
    desc = issue.get("description") or "No description"
    panel_content += f"\n[bold]Description:[/bold]\n{desc}"

    console.print(Panel(panel_content, title=f"Ticket: {issue['identifier']}", border_style="blue"))


# ============================================================================
# Sync Commands
# ============================================================================

sync_app = typer.Typer(help="[DEPRECATED] Sync commands - Linear is now source of truth", deprecated=True)
app.add_typer(sync_app, name="sync")


@sync_app.command("push")
def sync_push(
    component: Optional[str] = typer.Option(None, "-c", "--component", help="Only sync specific component"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be synced without making changes"),
    project_name: Optional[str] = typer.Option(None, "-p", "--project", help="Linear project name to add issues to"),
):
    """Push tickets to Linear (create new, update existing)."""
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        console.print("Run: [cyan]semfora-pm auth setup[/cyan]")
        raise typer.Exit(1)

    tickets = load_tickets(TICKETS_DIR)

    if component:
        tickets = [t for t in tickets if t.component.value == component]

    if not tickets:
        console.print("[yellow]No tickets to sync.[/yellow]")
        raise typer.Exit(0)

    # Get project ID if specified
    project_id = None
    if project_name:
        projects = client.get_projects(config.team_id)
        project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)
        if project:
            project_id = project["id"]
            console.print(f"[dim]Adding to project: {project['name']}[/dim]")
        else:
            console.print(f"[yellow]Warning: Project '{project_name}' not found. Creating issues without project.[/yellow]")

    # Get workflow states
    states = client.get_team_states(config.team_id)

    # Categorize tickets
    to_create = [t for t in tickets if not t.linear_id]
    to_update = [t for t in tickets if t.linear_id]

    console.print(f"\n[bold]Sync Summary:[/bold]")
    console.print(f"  New tickets: {len(to_create)}")
    console.print(f"  Existing tickets: {len(to_update)}")

    if dry_run:
        console.print("\n[yellow]Dry run mode - no changes will be made[/yellow]")
        for ticket in to_create:
            console.print(f"  [green]CREATE[/green] {ticket.id}: {ticket.title}")
        for ticket in to_update:
            console.print(f"  [blue]UPDATE[/blue] {ticket.id}: {ticket.title}")
        raise typer.Exit(0)

    if not to_create and not to_update:
        console.print("\n[green]Everything is in sync![/green]")
        raise typer.Exit(0)

    # Confirm
    if not typer.confirm(f"\nProceed with syncing {len(to_create)} new and {len(to_update)} existing tickets?"):
        raise typer.Exit(0)

    # Track which files need updating
    updated_tickets: dict[str, list[Ticket]] = {}  # filepath -> tickets

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Create new tickets
        if to_create:
            task = progress.add_task(f"Creating {len(to_create)} tickets...", total=len(to_create))
            for ticket in to_create:
                try:
                    # Map status to state ID
                    state_id = states.get(ticket.status.value)

                    issue = client.create_issue(
                        title=ticket.title,
                        description=ticket.description,
                        team_id=config.team_id,
                        priority=ticket.priority.to_linear(),
                        labels=ticket.labels,
                        estimate=ticket.estimate,
                        state_id=state_id,
                        project_id=project_id,
                    )

                    ticket.linear_id = issue["id"]
                    ticket.linear_url = issue["url"]

                    # Track for saving
                    filepath = TICKETS_DIR / f"{ticket.component.value}.yaml"
                    if filepath not in updated_tickets:
                        updated_tickets[filepath] = []
                    updated_tickets[filepath].append(ticket)

                    progress.console.print(f"  [green]✓[/green] Created {issue['identifier']}: {ticket.title[:40]}")

                except Exception as e:
                    progress.console.print(f"  [red]✗[/red] Failed {ticket.id}: {e}")

                progress.advance(task)

        # Update existing tickets
        if to_update:
            task = progress.add_task(f"Updating {len(to_update)} tickets...", total=len(to_update))
            for ticket in to_update:
                try:
                    state_id = states.get(ticket.status.value)

                    client.update_issue(
                        issue_id=ticket.linear_id,
                        title=ticket.title,
                        description=ticket.description,
                        priority=ticket.priority.to_linear(),
                        labels=ticket.labels,
                        estimate=ticket.estimate,
                        state_id=state_id,
                    )

                    progress.console.print(f"  [blue]✓[/blue] Updated {ticket.linear_id[:8]}: {ticket.title[:40]}")

                except Exception as e:
                    progress.console.print(f"  [red]✗[/red] Failed {ticket.id}: {e}")

                progress.advance(task)

    # Save updated tickets back to YAML
    if updated_tickets:
        console.print("\n[dim]Saving Linear IDs to YAML files...[/dim]")
        for filepath, file_tickets in updated_tickets.items():
            # Load all tickets for this file, update the ones we synced
            all_tickets = load_tickets(TICKETS_DIR)
            component = file_tickets[0].component
            component_tickets = [t for t in all_tickets if t.component == component]

            # Update with synced data
            for synced in file_tickets:
                for i, t in enumerate(component_tickets):
                    if t.id == synced.id:
                        component_tickets[i] = synced
                        break

            save_tickets(component_tickets, filepath)
            console.print(f"  [green]✓[/green] Saved {filepath.name}")

    console.print("\n[green]✓ Sync complete![/green]")


@sync_app.command("status")
def sync_status():
    """Show sync status of all tickets."""
    tickets = load_tickets(TICKETS_DIR)

    synced = [t for t in tickets if t.linear_id]
    unsynced = [t for t in tickets if not t.linear_id]

    console.print(f"\n[bold]Sync Status:[/bold]")
    console.print(f"  [green]Synced:[/green] {len(synced)}")
    console.print(f"  [yellow]Unsynced:[/yellow] {len(unsynced)}")

    if unsynced:
        console.print(f"\n[bold]Unsynced tickets:[/bold]")
        for ticket in unsynced[:10]:
            console.print(f"  • {ticket.id}: {ticket.title[:50]}")
        if len(unsynced) > 10:
            console.print(f"  [dim]...and {len(unsynced) - 10} more[/dim]")


@sync_app.command("reconcile")
def sync_reconcile(
    fix_labels: bool = typer.Option(False, "--fix-labels", help="Fix labels on matched issues"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show matches without making changes"),
):
    """Match existing Linear issues to YAML tickets and optionally fix labels.

    This command:
    1. Fetches all issues from Linear
    2. Matches them to YAML tickets by title
    3. Links them (saves linear_id to YAML)
    4. Optionally fixes labels (removes comma-separated, adds individual)
    """
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Load local tickets
    tickets = load_tickets(TICKETS_DIR)
    unsynced = [t for t in tickets if not t.linear_id]

    if not unsynced:
        console.print("[green]All tickets already synced![/green]")
        raise typer.Exit(0)

    console.print(f"[bold]Fetching issues from Linear...[/bold]")
    linear_issues = client.get_team_issues(config.team_id)
    console.print(f"  Found {len(linear_issues)} issues in Linear")

    # Build title -> issue map (normalize for matching)
    def normalize(s: str) -> str:
        return s.lower().strip()

    issue_by_title = {normalize(i["title"]): i for i in linear_issues}

    # Match tickets
    matches = []
    unmatched = []

    for ticket in unsynced:
        normalized_title = normalize(ticket.title)
        if normalized_title in issue_by_title:
            matches.append((ticket, issue_by_title[normalized_title]))
        else:
            unmatched.append(ticket)

    console.print(f"\n[bold]Match Results:[/bold]")
    console.print(f"  [green]Matched:[/green] {len(matches)}")
    console.print(f"  [yellow]Unmatched:[/yellow] {len(unmatched)}")

    if not matches:
        console.print("\n[yellow]No matches found. Issues may have different titles.[/yellow]")
        raise typer.Exit(0)

    # Show matches
    console.print(f"\n[bold]Matched tickets:[/bold]")
    for ticket, issue in matches[:10]:
        current_labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
        console.print(f"  • {ticket.id} ↔ {issue['identifier']}: {ticket.title[:40]}")
        if fix_labels:
            console.print(f"    [dim]Current labels: {current_labels}[/dim]")
            console.print(f"    [dim]New labels: {ticket.labels}[/dim]")

    if len(matches) > 10:
        console.print(f"  [dim]...and {len(matches) - 10} more[/dim]")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

    # Confirm
    action = "link and fix labels" if fix_labels else "link"
    if not typer.confirm(f"\nProceed to {action} {len(matches)} tickets?"):
        raise typer.Exit(0)

    # Process matches
    updated_by_component: dict[str, list[Ticket]] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Processing {len(matches)} tickets...", total=len(matches))

        for ticket, issue in matches:
            try:
                # Link ticket to Linear issue
                ticket.linear_id = issue["id"]
                ticket.linear_url = issue["url"]

                # Fix labels if requested
                if fix_labels and ticket.labels:
                    # Get correct label IDs
                    label_ids = [client.get_or_create_label(l, config.team_id) for l in ticket.labels]

                    # Update issue with correct labels
                    client.update_issue(
                        issue_id=issue["id"],
                        labels=ticket.labels,
                    )
                    progress.console.print(f"  [green]✓[/green] {issue['identifier']}: linked + labels fixed")
                else:
                    progress.console.print(f"  [blue]✓[/blue] {issue['identifier']}: linked")

                # Track for saving
                comp = ticket.component.value
                if comp not in updated_by_component:
                    updated_by_component[comp] = []
                updated_by_component[comp].append(ticket)

            except Exception as e:
                progress.console.print(f"  [red]✗[/red] {ticket.id}: {e}")

            progress.advance(task)

    # Save updated tickets
    console.print("\n[dim]Saving updates to YAML files...[/dim]")
    for comp, comp_tickets in updated_by_component.items():
        filepath = TICKETS_DIR / f"{comp}.yaml"

        # Load all tickets for this component
        all_tickets = load_tickets(TICKETS_DIR)
        component_tickets = [t for t in all_tickets if t.component.value == comp]

        # Update with linked data
        for updated in comp_tickets:
            for i, t in enumerate(component_tickets):
                if t.id == updated.id:
                    component_tickets[i] = updated
                    break

        save_tickets(component_tickets, filepath)
        console.print(f"  [green]✓[/green] Saved {filepath.name}")

    console.print(f"\n[green]✓ Reconciliation complete![/green]")
    console.print(f"  Linked: {len(matches)} tickets")
    if fix_labels:
        console.print(f"  Labels fixed: {len(matches)} issues")


@sync_app.command("cleanup-labels")
def sync_cleanup_labels(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted"),
):
    """Delete comma-separated labels that were created incorrectly.

    Finds labels like "engine, indexing, north-star" and deletes them.
    """
    client = get_client()

    console.print("[bold]Fetching labels from Linear...[/bold]")
    labels = client.get_labels()

    # Find comma-separated labels
    bad_labels = [l for l in labels if "," in l["name"]]

    if not bad_labels:
        console.print("[green]No comma-separated labels found![/green]")
        raise typer.Exit(0)

    console.print(f"\n[bold]Found {len(bad_labels)} bad labels:[/bold]")
    for label in bad_labels:
        console.print(f"  • {label['name']}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

    if not typer.confirm(f"\nDelete {len(bad_labels)} labels?"):
        raise typer.Exit(0)

    # Delete bad labels
    deleted = 0
    for label in bad_labels:
        if client.delete_label(label["id"]):
            console.print(f"  [green]✓[/green] Deleted: {label['name']}")
            deleted += 1
        else:
            console.print(f"  [red]✗[/red] Failed: {label['name']}")

    console.print(f"\n[green]✓ Deleted {deleted} labels[/green]")


# ============================================================================
# Import Commands
# ============================================================================

@app.command("import-csv", deprecated=True)
def import_csv(
    csv_file: Path = typer.Argument(..., help="CSV file to import"),
    component: str = typer.Option(..., "-c", "--component", help="Component for these tickets"),
):
    """[DEPRECATED] Import to YAML. Create tickets directly in Linear instead."""
    import csv

    if not csv_file.exists():
        console.print(f"[red]File not found:[/red] {csv_file}")
        raise typer.Exit(1)

    try:
        comp = Component(component)
    except ValueError:
        console.print(f"[red]Invalid component:[/red] {component}")
        console.print(f"Valid components: {', '.join(c.value for c in Component)}")
        raise typer.Exit(1)

    tickets = []
    ticket_num = 1

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse labels - split by comma and clean up
            labels_raw = row.get("Labels", "")
            labels = [l.strip() for l in labels_raw.split(",") if l.strip()]

            # Parse priority (1=Urgent, 2=High, 3=Medium, 4=Low)
            priority_val = int(row.get("Priority", 3))
            from .models.ticket import TicketPriority, TicketStatus
            priority = TicketPriority(priority_val) if priority_val in [1, 2, 3, 4] else TicketPriority.MEDIUM

            # Parse status
            status_str = row.get("Status", "Backlog")
            try:
                status = TicketStatus(status_str)
            except ValueError:
                status = TicketStatus.BACKLOG

            # Extract phase from labels if present
            phase = None
            phase_labels = [l for l in labels if l.startswith("phase-")]
            if phase_labels:
                phase = phase_labels[0]
                labels = [l for l in labels if l not in phase_labels]

            ticket = Ticket(
                id=f"{component}-{ticket_num:03d}",
                title=row["Title"],
                description=row["Description"],
                component=comp,
                priority=priority,
                status=status,
                labels=labels,
                estimate=int(row["Estimate"]) if row.get("Estimate") else None,
                phase=phase,
            )
            tickets.append(ticket)
            ticket_num += 1

    # Save to YAML
    TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = TICKETS_DIR / f"{component}.yaml"
    save_tickets(tickets, output_file)

    console.print(f"[green]✓[/green] Imported {len(tickets)} tickets to {output_file}")


# ============================================================================
# Project Commands
# ============================================================================

project_app = typer.Typer(help="Linear project commands")
app.add_typer(project_app, name="project")


@project_app.command("list")
def project_list():
    """List Linear projects."""
    client = get_client()
    projects = client.get_projects()

    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Linear Projects")
    table.add_column("Name", style="cyan")
    table.add_column("State", style="yellow")
    table.add_column("Teams", style="magenta")

    for project in projects:
        teams = ", ".join(t["name"] for t in project["teams"]["nodes"])
        table.add_row(project["name"], project["state"], teams)

    console.print(table)


@project_app.command("labels")
def project_labels():
    """List available labels."""
    client = get_client()
    labels = client.get_labels()

    if not labels:
        console.print("[yellow]No labels found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Linear Labels")
    table.add_column("Name", style="cyan")
    table.add_column("Color", style="yellow")

    for label in sorted(labels, key=lambda l: l["name"]):
        table.add_row(label["name"], label["color"])

    console.print(table)


@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: Optional[str] = typer.Option(None, "-d", "--description", help="Project description"),
):
    """Create a new Linear project."""
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    try:
        project = client.create_project(
            name=name,
            team_ids=[config.team_id],
            description=description,
        )
        console.print(f"[green]✓[/green] Created project: {project['name']}")
        console.print(f"  URL: {project['url']}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@project_app.command("add")
def project_add(
    project_name: str = typer.Argument(..., help="Project name"),
    component: Optional[str] = typer.Option(None, "-c", "--component", help="Add all tickets from component"),
    tickets: Optional[str] = typer.Option(None, "-t", "--tickets", help="Comma-separated ticket IDs or Linear identifiers"),
    label: Optional[str] = typer.Option(None, "-l", "--label", help="Add all tickets with this label"),
):
    """Add tickets to a Linear project."""
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Find project
    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)

    if not project:
        console.print(f"[red]Error:[/red] Project '{project_name}' not found.")
        console.print("Available projects:")
        for p in projects:
            console.print(f"  • {p['name']}")
        raise typer.Exit(1)

    # Collect tickets to add
    local_tickets = load_tickets(TICKETS_DIR)
    to_add = []

    if component:
        to_add = [t for t in local_tickets if t.component.value == component and t.linear_id]
    elif label:
        to_add = [t for t in local_tickets if label in t.labels and t.linear_id]
    elif tickets:
        ticket_ids = [t.strip() for t in tickets.split(",")]
        for tid in ticket_ids:
            # Check if it's a Linear identifier (SEM-5) or local ID (engine-001)
            if "-" in tid and tid.split("-")[0].isupper():
                # Linear identifier - get ID
                issue_id = client.get_issue_id_by_identifier(tid)
                if issue_id:
                    to_add.append(type('obj', (object,), {'linear_id': issue_id, 'id': tid})())
            else:
                # Local ticket ID
                ticket = next((t for t in local_tickets if t.id == tid), None)
                if ticket and ticket.linear_id:
                    to_add.append(ticket)

    if not to_add:
        console.print("[yellow]No tickets to add.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Adding {len(to_add)} tickets to project '{project['name']}'...")

    added = 0
    for ticket in to_add:
        try:
            client.add_issue_to_project(ticket.linear_id, project["id"])
            console.print(f"  [green]✓[/green] {ticket.id}")
            added += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {ticket.id}: {e}")

    console.print(f"\n[green]✓[/green] Added {added} tickets to '{project['name']}'")


# ============================================================================
# Link Commands
# ============================================================================

link_app = typer.Typer(help="Manage issue relationships")
app.add_typer(link_app, name="link")


@link_app.command("blocks")
def link_blocks(
    blocker: str = typer.Argument(..., help="Issue that blocks (e.g., SEM-5 or engine-001)"),
    blocked: str = typer.Argument(..., help="Issue that is blocked (e.g., SEM-6 or adk-001)"),
):
    """Create a 'blocks' relationship between issues."""
    client = get_client()
    local_tickets = load_tickets(TICKETS_DIR)

    def resolve_id(ref: str) -> Optional[str]:
        """Resolve ticket reference to Linear issue ID."""
        if "-" in ref and ref.split("-")[0].isupper():
            return client.get_issue_id_by_identifier(ref)
        else:
            ticket = next((t for t in local_tickets if t.id == ref), None)
            return ticket.linear_id if ticket else None

    blocker_id = resolve_id(blocker)
    blocked_id = resolve_id(blocked)

    if not blocker_id:
        console.print(f"[red]Error:[/red] Could not find issue '{blocker}'")
        raise typer.Exit(1)
    if not blocked_id:
        console.print(f"[red]Error:[/red] Could not find issue '{blocked}'")
        raise typer.Exit(1)

    try:
        client.create_issue_relation(blocker_id, blocked_id, "blocks")
        console.print(f"[green]✓[/green] {blocker} blocks {blocked}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@link_app.command("related")
def link_related(
    issue1: str = typer.Argument(..., help="First issue (e.g., SEM-5)"),
    issue2: str = typer.Argument(..., help="Second issue (e.g., SEM-6)"),
):
    """Create a 'related' relationship between issues."""
    client = get_client()
    local_tickets = load_tickets(TICKETS_DIR)

    def resolve_id(ref: str) -> Optional[str]:
        if "-" in ref and ref.split("-")[0].isupper():
            return client.get_issue_id_by_identifier(ref)
        else:
            ticket = next((t for t in local_tickets if t.id == ref), None)
            return ticket.linear_id if ticket else None

    id1 = resolve_id(issue1)
    id2 = resolve_id(issue2)

    if not id1:
        console.print(f"[red]Error:[/red] Could not find issue '{issue1}'")
        raise typer.Exit(1)
    if not id2:
        console.print(f"[red]Error:[/red] Could not find issue '{issue2}'")
        raise typer.Exit(1)

    try:
        client.create_issue_relation(id1, id2, "related")
        console.print(f"[green]✓[/green] {issue1} ↔ {issue2} (related)")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@link_app.command("bulk")
def link_bulk(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be linked"),
):
    """Create links from depends_on/blocks fields in YAML tickets."""
    client = get_client()
    tickets = load_tickets(TICKETS_DIR)

    # Build ticket ID -> linear_id map
    id_map = {t.id: t.linear_id for t in tickets if t.linear_id}

    relations = []
    for ticket in tickets:
        if not ticket.linear_id:
            continue

        # depends_on means THIS ticket is blocked by THOSE
        for dep_id in ticket.depends_on:
            if dep_id in id_map:
                relations.append((id_map[dep_id], ticket.linear_id, "blocks", f"{dep_id} blocks {ticket.id}"))

        # blocks means THIS ticket blocks THOSE
        for block_id in ticket.blocks:
            if block_id in id_map:
                relations.append((ticket.linear_id, id_map[block_id], "blocks", f"{ticket.id} blocks {block_id}"))

    if not relations:
        console.print("[yellow]No relationships defined in YAML tickets.[/yellow]")
        console.print("[dim]Add 'depends_on' or 'blocks' fields to ticket definitions.[/dim]")
        raise typer.Exit(0)

    console.print(f"[bold]Found {len(relations)} relationships to create:[/bold]")
    for _, _, _, desc in relations:
        console.print(f"  • {desc}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

    if not typer.confirm(f"\nCreate {len(relations)} relationships?"):
        raise typer.Exit(0)

    created = 0
    for blocker_id, blocked_id, rel_type, desc in relations:
        try:
            client.create_issue_relation(blocker_id, blocked_id, rel_type)
            console.print(f"  [green]✓[/green] {desc}")
            created += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {desc}: {e}")

    console.print(f"\n[green]✓[/green] Created {created} relationships")


# ============================================================================
# Labels Commands
# ============================================================================

labels_app = typer.Typer(help="Label management commands")
app.add_typer(labels_app, name="labels")

# Color scheme for label categories
LABEL_COLOR_SCHEME = {
    # Components - distinct colors for each
    "engine": "#E07C24",    # Orange
    "adk": "#8B5CF6",       # Purple
    "cli": "#10B981",       # Emerald
    "pm": "#EC4899",        # Pink
    "docs": "#6B7280",      # Gray
    "infra": "#64748B",     # Slate

    # Priority/Importance - warm colors
    "high-priority": "#EF4444",  # Red
    "north-star": "#F59E0B",     # Amber
    "blocker": "#DC2626",        # Dark red
    "quick-win": "#22C55E",      # Green

    # Work type - blues and teals
    "performance": "#0EA5E9",    # Sky blue
    "testing": "#14B8A6",        # Teal
    "validation": "#06B6D4",     # Cyan
    "improvement": "#3B82F6",    # Blue
    "code-quality": "#6366F1",   # Indigo

    # Feature categories - varied
    "indexing": "#A855F7",       # Violet
    "git": "#F97316",            # Orange
    "mcp": "#84CC16",            # Lime
    "monorepo": "#78716C",       # Stone
    "models": "#D946EF",         # Fuchsia
    "config": "#94A3B8",         # Slate light
    "persistence": "#7C3AED",    # Purple dark
    "streaming": "#2DD4BF",      # Teal light
    "caching": "#60A5FA",        # Blue light
    "cost": "#FBBF24",           # Yellow
    "offline": "#4ADE80",        # Green light

    # UI/UX
    "ui": "#FB7185",             # Rose
    "ux": "#F472B6",             # Pink light
    "edits": "#818CF8",          # Indigo light
    "navigation": "#34D399",     # Emerald light
    "visualization": "#A78BFA",  # Purple light
    "settings": "#9CA3AF",       # Gray light
    "error-handling": "#FB923C", # Orange light

    # Phase markers
    "planned": "#A3E635",        # Lime light
    "phase-1": "#22D3EE",        # Cyan
    "phase-2": "#38BDF8",        # Sky
    "phase-4": "#818CF8",        # Indigo light
    "phase-5": "#C084FC",        # Purple light
    "ongoing": "#FCD34D",        # Yellow light

    # Meta
    "core": "#EF4444",           # Red (important)
    "distribution": "#F59E0B",   # Amber
    "prompt-architecture": "#8B5CF6",  # Purple
    "context": "#0891B2",        # Cyan dark
    "memory": "#7C3AED",         # Violet dark
    "orchestration": "#6D28D9",  # Purple dark
    "verification": "#059669",   # Emerald dark
    "confidence": "#0D9488",     # Teal dark
    "types": "#4F46E5",          # Indigo dark
}


@labels_app.command("audit")
def labels_audit(
    apply: bool = typer.Option(False, "--apply", help="Apply color changes"),
    show_invalid: bool = typer.Option(False, "--show-invalid", help="Show comma-separated labels"),
):
    """Audit labels and assign colors based on category.

    Scans all labels, identifies their category, and assigns appropriate colors.
    Comma-separated labels (improperly imported) are skipped but can be shown.
    """
    client = get_client()

    console.print("[bold]Fetching labels from Linear...[/bold]")
    labels = client.get_labels()

    # Separate valid and invalid labels
    valid_labels = []
    invalid_labels = []

    for label in labels:
        if "," in label["name"]:
            invalid_labels.append(label)
        else:
            valid_labels.append(label)

    console.print(f"  Found {len(valid_labels)} valid labels")
    console.print(f"  Found {len(invalid_labels)} comma-separated labels (skipped)")

    if show_invalid and invalid_labels:
        console.print("\n[yellow]Comma-separated labels (invalid):[/yellow]")
        for label in invalid_labels:
            console.print(f"  • {label['name']}")

    # Analyze and categorize labels
    table = Table(title="Label Color Audit")
    table.add_column("Label", style="white")
    table.add_column("Current Color", style="dim")
    table.add_column("New Color", style="cyan")
    table.add_column("Status", style="green")

    changes = []

    for label in sorted(valid_labels, key=lambda l: l["name"].lower()):
        name = label["name"].lower()
        current_color = label.get("color", "#default")

        # Find matching color scheme
        new_color = None
        for key, color in LABEL_COLOR_SCHEME.items():
            if name == key or name.startswith(key) or key in name:
                new_color = color
                break

        if new_color is None:
            # Default color for unmatched labels
            new_color = "#6B7280"  # Gray

        # Check if change is needed
        needs_change = current_color.lower() != new_color.lower()

        status = "✓ OK" if not needs_change else "→ UPDATE"
        status_style = "green" if not needs_change else "yellow"

        table.add_row(
            label["name"],
            f"[{current_color}]●[/] {current_color}",
            f"[{new_color}]●[/] {new_color}",
            f"[{status_style}]{status}[/{status_style}]",
        )

        if needs_change:
            changes.append((label["id"], label["name"], new_color))

    console.print(table)

    if not changes:
        console.print("\n[green]All labels have correct colors![/green]")
        return

    console.print(f"\n[bold]{len(changes)} labels need color updates[/bold]")

    if not apply:
        console.print("\n[dim]Run with --apply to update colors[/dim]")
        return

    # Apply changes
    if not typer.confirm(f"Apply color changes to {len(changes)} labels?"):
        raise typer.Exit(0)

    updated = 0
    for label_id, name, color in changes:
        if client.update_label(label_id, color=color):
            console.print(f"  [green]✓[/green] {name} → {color}")
            updated += 1
        else:
            console.print(f"  [red]✗[/red] {name}")

    console.print(f"\n[green]✓ Updated {updated}/{len(changes)} labels[/green]")


@labels_app.command("list")
def labels_list():
    """List all labels with their colors."""
    client = get_client()
    labels = client.get_labels()

    # Filter out comma-separated
    valid_labels = [l for l in labels if "," not in l["name"]]

    table = Table(title="Linear Labels")
    table.add_column("Name", style="cyan")
    table.add_column("Color", style="yellow")
    table.add_column("Preview")

    for label in sorted(valid_labels, key=lambda l: l["name"].lower()):
        color = label.get("color", "#6B7280")
        table.add_row(
            label["name"],
            color,
            f"[{color}]████[/]",
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(valid_labels)} labels[/dim]")


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
):
    """Plan a sprint by moving tickets from Backlog to Todo.

    Use Linear identifiers (e.g., SEM-32, SEM-33) directly.
    """
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    ticket_ids = [t.strip() for t in tickets.split(",")]

    # Fetch issues directly from Linear
    all_issues = client.get_team_issues(config.team_id)
    issue_by_id = {i["identifier"]: i for i in all_issues}

    # Resolve tickets
    sprint_issues = []
    for tid in ticket_ids:
        if tid in issue_by_id:
            sprint_issues.append(issue_by_id[tid])
        else:
            console.print(f"[yellow]Warning:[/yellow] {tid} not found in Linear")

    if not sprint_issues:
        console.print("[red]No valid tickets found[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Sprint: {name}[/bold]")
    console.print(f"Tickets: {len(sprint_issues)}")

    table = Table(title=f"Sprint Plan: {name}")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Priority", style="yellow")
    table.add_column("Estimate", style="blue")
    table.add_column("State", style="magenta")

    total_estimate = 0

    for issue in sprint_issues:
        estimate = issue.get("estimate") or 0
        total_estimate += estimate
        priority = issue.get("priority", 0)
        priority_str = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}.get(priority, str(priority))

        table.add_row(
            issue["identifier"],
            issue["title"][:40] + "..." if len(issue["title"]) > 40 else issue["title"],
            priority_str,
            str(estimate) if estimate else "—",
            issue["state"]["name"],
        )

    console.print(table)
    console.print(f"\n[dim]Total estimate: {total_estimate} points[/dim]")

    if dry_run:
        console.print("\n[dim]Dry run - no changes made[/dim]")
        raise typer.Exit(0)

    # Move tickets to Todo state
    states = client.get_team_states(config.team_id)
    todo_state_id = states.get("Todo")

    if not todo_state_id:
        console.print("[red]Error:[/red] 'Todo' state not found")
        raise typer.Exit(1)

    if not typer.confirm(f"\nMove {len(sprint_issues)} tickets to 'Todo' state?"):
        raise typer.Exit(0)

    moved = 0
    for issue in sprint_issues:
        try:
            client.update_issue(issue["id"], state_id=todo_state_id)
            console.print(f"  [green]✓[/green] {issue['identifier']}: {issue['title'][:40]}")
            moved += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {issue['identifier']}: {e}")

    console.print(f"\n[green]✓ Moved {moved} tickets to Todo[/green]")


@sprint_app.command("suggest")
def sprint_suggest(
    points: int = typer.Option(20, "-p", "--points", help="Target story points for sprint"),
    label: Optional[str] = typer.Option(None, "-l", "--label", help="Filter by label"),
):
    """Suggest tickets for next sprint based on priority.

    Queries Linear backlog and suggests tickets that fit the point budget.
    """
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Fetch issues directly from Linear
    all_issues = client.get_team_issues(config.team_id)

    # Filter to backlog tickets
    backlog = [i for i in all_issues if i["state"]["name"] == "Backlog"]

    if label:
        backlog = [i for i in backlog if any(l["name"] == label for l in i.get("labels", {}).get("nodes", []))]

    if not backlog:
        console.print("[yellow]No backlog tickets found[/yellow]")
        raise typer.Exit(0)

    # Sort by priority (lower is higher priority), then by estimate
    sorted_issues = sorted(
        backlog,
        key=lambda i: (i.get("priority", 4), -(i.get("estimate") or 0))
    )

    # Greedily select tickets
    suggested = []
    current_points = 0

    for issue in sorted_issues:
        if current_points >= points:
            break
        estimate = issue.get("estimate") or 2  # Default estimate
        if current_points + estimate <= points:
            suggested.append(issue)
            current_points += estimate

    # Display suggestions
    table = Table(title=f"Suggested Sprint ({current_points}/{points} points)")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Priority", style="yellow")
    table.add_column("Estimate", style="blue")
    table.add_column("Labels", style="dim")

    for issue in suggested:
        labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])][:3]
        labels_str = ", ".join(labels) if labels else "—"
        priority = issue.get("priority", 0)
        priority_str = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}.get(priority, str(priority))

        table.add_row(
            issue["identifier"],
            issue["title"][:45] + "..." if len(issue["title"]) > 45 else issue["title"],
            priority_str,
            str(issue.get("estimate") or "—"),
            labels_str,
        )

    console.print(table)

    # Show command to plan this sprint
    ids = ",".join(i["identifier"] for i in suggested)
    console.print(f"\n[dim]To plan this sprint, run:[/dim]")
    console.print(f"  [cyan]semfora-pm sprint plan sprint-X -t \"{ids}\"[/cyan]")

    # Show what was excluded
    excluded = [i for i in sorted_issues if i not in suggested][:5]
    if excluded:
        console.print(f"\n[dim]Next up (over budget):[/dim]")
        for i in excluded:
            console.print(f"  • {i['identifier']}: {i['title'][:40]}")


@sprint_app.command("status")
def sprint_status():
    """Show current sprint status (tickets in Todo/In Progress)."""
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    issues = client.get_team_issues(config.team_id)

    # Group by state
    todo = [i for i in issues if i["state"]["name"] == "Todo"]
    in_progress = [i for i in issues if i["state"]["name"] == "In Progress"]
    in_review = [i for i in issues if i["state"]["name"] == "In Review"]

    console.print("\n[bold]Current Sprint Status[/bold]\n")

    if in_progress:
        console.print(f"[yellow]In Progress ({len(in_progress)}):[/yellow]")
        for issue in in_progress:
            priority = issue.get("priority", 0)
            priority_icon = "🔴" if priority <= 1 else "🟡" if priority == 2 else "⚪"
            console.print(f"  {priority_icon} {issue['identifier']}: {issue['title'][:50]}")

    if in_review:
        console.print(f"\n[blue]In Review ({len(in_review)}):[/blue]")
        for issue in in_review:
            console.print(f"  📝 {issue['identifier']}: {issue['title'][:50]}")

    if todo:
        console.print(f"\n[cyan]Todo ({len(todo)}):[/cyan]")
        for issue in todo[:10]:
            priority = issue.get("priority", 0)
            priority_icon = "🔴" if priority <= 1 else "🟡" if priority == 2 else "⚪"
            console.print(f"  {priority_icon} {issue['identifier']}: {issue['title'][:50]}")
        if len(todo) > 10:
            console.print(f"  [dim]...and {len(todo) - 10} more[/dim]")

    total_active = len(in_progress) + len(in_review) + len(todo)
    console.print(f"\n[dim]Total active: {total_active} tickets[/dim]")


# ============================================================================
# Project Description Command
# ============================================================================

@project_app.command("describe")
def project_describe(
    project_name: str = typer.Argument(..., help="Project name"),
    description: str = typer.Option(..., "-d", "--description", help="Project description"),
):
    """Update a project's description."""
    client = get_client()

    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)

    if not project:
        console.print(f"[red]Error:[/red] Project '{project_name}' not found")
        raise typer.Exit(1)

    try:
        client.update_project(project["id"], description=description)
        console.print(f"[green]✓[/green] Updated description for '{project['name']}'")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@project_app.command("show")
def project_show(
    project_name: str = typer.Argument(..., help="Project name"),
):
    """Show project details including tickets."""
    client = get_client()

    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)

    if not project:
        console.print(f"[red]Error:[/red] Project '{project_name}' not found")
        raise typer.Exit(1)

    details = client.get_project_details(project["id"])

    if not details:
        console.print("[red]Error:[/red] Could not fetch project details")
        raise typer.Exit(1)

    # Display project info
    panel_content = f"""[bold]{details['name']}[/bold]

[cyan]State:[/cyan] {details['state']}
[cyan]URL:[/cyan] {details.get('url', '—')}
[cyan]Target Date:[/cyan] {details.get('targetDate', '—')}

[cyan]Description:[/cyan]
{details.get('description', 'No description')}
"""
    console.print(Panel(panel_content, title="Project Details", border_style="blue"))

    # Show tickets
    issues = details.get("issues", {}).get("nodes", [])
    if issues:
        table = Table(title=f"Issues ({len(issues)})")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("State", style="yellow")
        table.add_column("Priority", style="magenta")

        for issue in issues:
            priority = issue.get("priority", 0)
            priority_str = {0: "None", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}.get(priority, str(priority))
            table.add_row(
                issue["identifier"],
                issue["title"][:50] + "..." if len(issue["title"]) > 50 else issue["title"],
                issue["state"]["name"],
                priority_str,
            )

        console.print(table)


# ============================================================================
# Tickets Commands (Bulk Creation for AI Agents)
# ============================================================================

tickets_app = typer.Typer(help="Ticket creation and search (optimized for AI agents)")
app.add_typer(tickets_app, name="tickets")


@tickets_app.command("search")
def tickets_search(
    query: str = typer.Argument(..., help="Search query for ticket titles"),
    limit: int = typer.Option(20, "--limit", help="Maximum results"),
):
    """Search for existing tickets by title.

    Use this BEFORE creating tickets to check for duplicates.
    This is especially important for AI agents planning features.
    """
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(f"Searching for '{query}'...", total=None)
        issues = client.search_issues(query, config.team_id, limit)

    if not issues:
        console.print(f"[green]No existing tickets match '{query}'[/green]")
        raise typer.Exit(0)

    console.print(f"\n[yellow]Found {len(issues)} potentially similar tickets:[/yellow]\n")

    for issue in issues:
        state = issue["state"]["name"]
        state_color = "green" if state == "Done" else "yellow" if state == "In Progress" else "cyan"
        labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])][:3]
        labels_str = f" [{', '.join(labels)}]" if labels else ""

        console.print(f"  [{state_color}]{issue['identifier']}[/]: {issue['title'][:60]}")
        console.print(f"      State: {state}{labels_str}")

    console.print(f"\n[bold yellow]⚠️  Review these before creating new tickets to avoid duplicates![/bold yellow]")


@tickets_app.command("update")
def tickets_update(
    identifier: str = typer.Argument(..., help="Linear ticket identifier (e.g., SEM-123)"),
    state: Optional[str] = typer.Option(None, "-s", "--state", help="New state (Backlog, Todo, 'In Progress', 'In Review', Done, Canceled)"),
    priority: Optional[int] = typer.Option(None, "-p", "--priority", help="New priority (1=Urgent, 2=High, 3=Medium, 4=Low)"),
    estimate: Optional[int] = typer.Option(None, "-e", "--estimate", help="Story point estimate"),
    add_labels: Optional[str] = typer.Option(None, "--add-labels", help="Comma-separated labels to add"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description (use @filename to read from file)"),
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
    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
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
        states = client.get_team_states(config.team_id)
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
    file: Path = typer.Argument(..., help="YAML/JSON file with ticket definitions"),
    skip_duplicates: bool = typer.Option(False, "--skip-duplicates", help="Skip duplicate check"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be created without creating"),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompts"),
):
    """Create multiple tickets with relationships from a YAML/JSON file.

    This command is designed for AI agents planning features. It:
    1. Checks for potential duplicates (unless --skip-duplicates)
    2. Creates all tickets in dependency order
    3. Sets up relationships (blocks, blocked_by, related)
    4. Optionally adds to project/milestone and sprint

    Example YAML format:

    \b
    project: "My Project"        # Optional: add all to this project
    milestone: "v1.0"            # Optional: add all to this milestone
    sprint: true                 # Optional: move all to Todo state

    \b
    tickets:
      - id: main-feature         # Temporary ID for references
        title: "Main feature"
        description: "Description here"
        priority: 2              # 1=Urgent, 2=High, 3=Medium, 4=Low
        estimate: 5
        labels: [feature, core]

    \b
      - id: subtask-1
        title: "Subtask 1"
        blocked_by: [main-feature]  # References temp ID
        priority: 3
        estimate: 3

    \b
      - id: subtask-2
        title: "Subtask 2"
        blocked_by: [subtask-1]
        related: [main-feature]
    """
    import yaml
    import json

    client = get_client()
    config = LinearConfig.load()

    if not config.team_id:
        console.print("[red]Error:[/red] No default team configured.")
        raise typer.Exit(1)

    # Load the file
    if not file.exists():
        console.print(f"[red]Error:[/red] File not found: {file}")
        raise typer.Exit(1)

    content = file.read_text()
    try:
        if file.suffix in [".yaml", ".yml"]:
            data = yaml.safe_load(content)
        else:
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

    # Validate references
    for ticket in tickets_data:
        for ref in ticket.get("blocked_by", []) + ticket.get("blocks", []) + ticket.get("related", []):
            if ref not in temp_ids:
                console.print(f"[red]Error:[/red] Unknown reference '{ref}' in ticket '{ticket['id']}'")
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
            similar = client.search_issues_multi(titles, config.team_id)

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
        projects = client.get_projects(config.team_id)
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
        states = client.get_team_states(config.team_id)
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
                    team_id=config.team_id,
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
    relations_to_create = []
    for ticket in tickets_data:
        if ticket["id"] not in id_mapping:
            continue

        linear_id = id_mapping[ticket["id"]]["id"]

        # blocked_by -> the other ticket blocks this one
        for blocker_temp_id in ticket.get("blocked_by", []):
            if blocker_temp_id in id_mapping:
                relations_to_create.append({
                    "from": id_mapping[blocker_temp_id],
                    "to": id_mapping[ticket["id"]],
                    "type": "blocks",
                    "desc": f"{id_mapping[blocker_temp_id]['identifier']} blocks {id_mapping[ticket['id']]['identifier']}",
                })

        # blocks -> this ticket blocks the other
        for blocked_temp_id in ticket.get("blocks", []):
            if blocked_temp_id in id_mapping:
                relations_to_create.append({
                    "from": id_mapping[ticket["id"]],
                    "to": id_mapping[blocked_temp_id],
                    "type": "blocks",
                    "desc": f"{id_mapping[ticket['id']]['identifier']} blocks {id_mapping[blocked_temp_id]['identifier']}",
                })

        # related
        for related_temp_id in ticket.get("related", []):
            if related_temp_id in id_mapping:
                # Avoid duplicate relations (A related B == B related A)
                pair = tuple(sorted([ticket["id"], related_temp_id]))
                if not any(
                    r["type"] == "related" and tuple(sorted([r["from"]["identifier"], r["to"]["identifier"]])) == (id_mapping[pair[0]]["identifier"], id_mapping[pair[1]]["identifier"])
                    for r in relations_to_create
                ):
                    relations_to_create.append({
                        "from": id_mapping[ticket["id"]],
                        "to": id_mapping[related_temp_id],
                        "type": "related",
                        "desc": f"{id_mapping[ticket['id']]['identifier']} <-> {id_mapping[related_temp_id]['identifier']} (related)",
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
