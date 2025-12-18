"""Main TUI Application."""

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from ..db.connection import Database
from ..local_tickets import LocalTicketManager
from ..dependencies import DependencyManager
from ..external_items import ExternalItemsManager
from ..pm_config import resolve_context, PMContext

from .state import AppState
from .providers import ProviderAdapter, create_provider_adapter
from .screens import DashboardScreen, LocalTicketsScreen, DependenciesScreen, HelpScreen, CreateLocalTicketModal


class SemforaPMApp(App):
    """Semfora PM Terminal User Interface."""

    TITLE = "Semfora PM"
    SUB_TITLE = "Project Management TUI"

    CSS = """
    Screen {
        background: $surface;
    }

    #welcome-container {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #welcome-text {
        text-align: center;
        padding: 2;
        border: solid $primary;
        background: $surface;
    }

    /* Status badges */
    .badge-pending { color: $text-muted; }
    .badge-progress { color: $primary; text-style: bold; }
    .badge-complete { color: $success; }
    .badge-blocked { color: $warning; text-style: bold; }
    .badge-canceled { color: $text-muted; text-style: italic; }
    .badge-orphaned { color: $warning; text-style: italic; }

    /* Priority indicators */
    .priority-urgent { color: $error; text-style: bold; }
    .priority-high { color: $warning; }
    .priority-medium { color: $text; }
    .priority-low { color: $text-muted; }
    .priority-none { color: $text-muted; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("d", "switch_mode('dashboard')", "Dashboard", show=True),
        Binding("t", "switch_mode('tickets')", "Tickets", show=True),
        Binding("g", "switch_mode('dependencies')", "Graph", show=True),
        Binding("n", "new_ticket", "New", show=True),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("ctrl+r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, path: Path | None = None):
        """Initialize the TUI application.

        Args:
            path: Optional directory path for PM context resolution.
        """
        super().__init__()
        self.context_path = path or Path.cwd()

        # State management
        self.state = AppState()

        # Lazy-initialized components
        self._pm_context: Optional[PMContext] = None
        self._db: Optional[Database] = None
        self._project_id: Optional[str] = None
        self._ticket_manager: Optional[LocalTicketManager] = None
        self._dep_manager: Optional[DependencyManager] = None
        self._ext_manager: Optional[ExternalItemsManager] = None
        self._provider: Optional[ProviderAdapter] = None

    def _init_managers(self) -> None:
        """Initialize database and managers."""
        if self._db is not None:
            return

        self._pm_context = resolve_context(self.context_path)
        db_path = self._pm_context.get_db_path()

        self._db = Database(db_path)
        self._project_id = self._ensure_project(self._pm_context)

        # Initialize managers
        self._ticket_manager = LocalTicketManager(self._db, self._project_id)
        self._dep_manager = DependencyManager(self._db, self._project_id)
        self._ext_manager = ExternalItemsManager(self._db, self._project_id)

        # Initialize provider adapter
        self._provider = create_provider_adapter(self._pm_context, self._ext_manager)

    def _ensure_project(self, context: PMContext) -> str:
        """Ensure project exists in database, return project_id."""
        import uuid
        from datetime import datetime

        config_path = str(context.config_path) if context.config_path else "default"

        with self._db.connection() as conn:
            # Check if project exists
            row = conn.execute(
                "SELECT id FROM projects WHERE config_path = ?",
                (config_path,)
            ).fetchone()

            if row:
                return row["id"]

            # Create new project
            project_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            conn.execute(
                """INSERT INTO projects (id, name, config_path, provider,
                   provider_team_id, provider_project_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    context.team_name or "Local Project",
                    config_path,
                    context.provider or "local",
                    context.team_id,
                    context.project_id,
                    now,
                    now,
                )
            )
            conn.commit()
            return project_id

    @property
    def pm_context(self) -> PMContext:
        """Get the PM context, initializing if needed."""
        self._init_managers()
        return self._pm_context

    @property
    def ticket_manager(self) -> LocalTicketManager:
        """Get the local ticket manager, initializing if needed."""
        self._init_managers()
        return self._ticket_manager

    @property
    def dep_manager(self) -> DependencyManager:
        """Get the dependency manager, initializing if needed."""
        self._init_managers()
        return self._dep_manager

    @property
    def ext_manager(self) -> ExternalItemsManager:
        """Get the external items manager, initializing if needed."""
        self._init_managers()
        return self._ext_manager

    @property
    def provider(self) -> ProviderAdapter:
        """Get the provider adapter, initializing if needed."""
        self._init_managers()
        return self._provider

    def compose(self) -> ComposeResult:
        """Create the initial UI."""
        yield Header()
        yield Static(
            "[bold]Welcome to Semfora PM TUI[/bold]\n\n"
            "Press [bold cyan]d[/] for Dashboard\n"
            "Press [bold cyan]t[/] for Tickets\n"
            "Press [bold cyan]g[/] for Dependency Graph\n"
            "Press [bold cyan]n[/] to create a new ticket\n"
            "Press [bold cyan]?[/] for help\n"
            "Press [bold cyan]q[/] to quit",
            id="welcome-text",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Initialize when the app is mounted."""
        # Pre-initialize managers
        self._init_managers()

        # Update subtitle with provider info
        provider_name = self.provider.get_provider_name()
        connected = self.provider.is_connected()
        status = "connected" if connected else "offline"
        self.sub_title = f"{provider_name} ({status})"

    def action_switch_mode(self, mode: str) -> None:
        """Switch between TUI modes/screens."""
        self.state.current_screen = mode

        if mode == "dashboard":
            self.push_screen(DashboardScreen())
        elif mode == "tickets":
            self.push_screen(LocalTicketsScreen())
        elif mode == "dependencies":
            self.push_screen(DependenciesScreen())
        else:
            self.notify(f"Unknown mode: {mode}")

    def action_new_ticket(self) -> None:
        """Create a new local ticket."""
        def on_ticket_created(ticket):
            if ticket:
                self.notify(f"Created: {ticket.title[:30]}...")
                # Refresh data if needed
                self.state.tickets_cache.clear()

        self.push_screen(CreateLocalTicketModal(), on_ticket_created)

    def action_show_help(self) -> None:
        """Show help screen with all keybindings."""
        self.push_screen(HelpScreen())

    def action_refresh(self) -> None:
        """Refresh data from database."""
        # Reset all cached components
        self._db = None
        self._pm_context = None
        self._project_id = None
        self._ticket_manager = None
        self._dep_manager = None
        self._ext_manager = None
        self._provider = None

        # Re-initialize
        self._init_managers()

        # Clear state caches
        self.state.tickets_cache.clear()
        self.state.ready_work_cache.clear()

        self.notify("Data refreshed")

    def refresh_tickets(self) -> None:
        """Refresh the tickets cache."""
        self.state.tickets_cache = self.ticket_manager.list(
            status=self.state.status_filter,
            include_completed=self.state.show_completed,
        )

    def refresh_ready_work(self) -> None:
        """Refresh the ready work cache."""
        self.state.ready_work_cache = self.dep_manager.get_ready_work(
            include_local=True,
        )
