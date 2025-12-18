"""Provider panel widget for displaying linked ticket details."""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Label
from textual.widget import Widget

from ..providers import TicketDetails, ProviderAdapter


class ProviderPanel(Widget):
    """Widget displaying linked ticket details from a provider."""

    DEFAULT_CSS = """
    ProviderPanel {
        width: 100%;
        height: auto;
        padding: 1;
        border: solid $primary;
        background: $surface;
    }

    ProviderPanel.hidden {
        display: none;
    }

    ProviderPanel .panel-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $surface-lighten-1;
        margin-bottom: 1;
    }

    ProviderPanel .ticket-id {
        color: $primary;
        text-style: bold;
    }

    ProviderPanel .ticket-title {
        width: 100%;
        padding: 0 0 1 0;
    }

    ProviderPanel .ticket-meta {
        width: 100%;
        height: auto;
    }

    ProviderPanel .meta-row {
        width: 100%;
        height: 1;
    }

    ProviderPanel .meta-label {
        width: 12;
        color: $text-muted;
    }

    ProviderPanel .meta-value {
        width: 1fr;
    }

    ProviderPanel .ticket-description {
        width: 100%;
        height: auto;
        max-height: 10;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
        margin-top: 1;
        color: $text-muted;
    }

    ProviderPanel .cache-indicator {
        width: 100%;
        text-align: right;
        color: $text-muted;
        text-style: italic;
    }

    ProviderPanel .no-ticket {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(self, provider_id: str | None = None, **kwargs):
        """Initialize the provider panel.

        Args:
            provider_id: Optional initial provider ID to display
        """
        super().__init__(**kwargs)
        self._provider_id = provider_id
        self._ticket: TicketDetails | None = None

    def compose(self) -> ComposeResult:
        """Create the panel UI."""
        yield Static("Linked Ticket", classes="panel-header")
        yield Static("No ticket linked", classes="no-ticket", id="no-ticket")
        yield Vertical(id="ticket-content")

    def on_mount(self) -> None:
        """Initialize the panel."""
        if self._provider_id:
            self.load_ticket(self._provider_id)
        else:
            self._show_no_ticket()

    def _show_no_ticket(self) -> None:
        """Show the 'no ticket' message."""
        self.query_one("#no-ticket").display = True
        self.query_one("#ticket-content").display = False

    def _show_ticket_content(self) -> None:
        """Show the ticket content."""
        self.query_one("#no-ticket").display = False
        self.query_one("#ticket-content").display = True

    def load_ticket(self, provider_id: str) -> None:
        """Load and display ticket details.

        Args:
            provider_id: The provider's ticket ID (e.g., "SEM-123")
        """
        self._provider_id = provider_id

        # Get provider from app
        app = self.app
        if hasattr(app, "provider"):
            self._ticket = app.provider.get_ticket(provider_id)

        if self._ticket:
            self._render_ticket()
        else:
            self._show_no_ticket()

    def _render_ticket(self) -> None:
        """Render the ticket details."""
        if not self._ticket:
            return

        self._show_ticket_content()

        content = self.query_one("#ticket-content", Vertical)
        content.remove_children()

        # Ticket ID and title
        content.mount(Static(f"[bold]{self._ticket.provider_id}[/bold]", classes="ticket-id"))
        content.mount(Static(self._ticket.title, classes="ticket-title"))

        # Meta information
        meta = Vertical(classes="ticket-meta")

        if self._ticket.status:
            meta.mount(self._meta_row("Status:", self._ticket.status))

        if self._ticket.priority is not None:
            from ..state import get_priority_label
            priority_label = get_priority_label(self._ticket.priority)
            meta.mount(self._meta_row("Priority:", priority_label))

        if self._ticket.assignee:
            meta.mount(self._meta_row("Assignee:", self._ticket.assignee))

        if self._ticket.epic_name:
            meta.mount(self._meta_row("Epic:", self._ticket.epic_name))

        if self._ticket.labels:
            labels_str = ", ".join(self._ticket.labels[:5])
            meta.mount(self._meta_row("Labels:", labels_str))

        content.mount(meta)

        # Description (truncated)
        if self._ticket.description:
            desc = self._ticket.description
            if len(desc) > 200:
                desc = desc[:200] + "..."
            content.mount(Static(desc, classes="ticket-description"))

        # Cache indicator
        if self._ticket.is_cached:
            content.mount(Static("(cached)", classes="cache-indicator"))

    def _meta_row(self, label: str, value: str) -> Horizontal:
        """Create a metadata row."""
        row = Horizontal(classes="meta-row")
        row.mount(Static(label, classes="meta-label"))
        row.mount(Static(value, classes="meta-value"))
        return row

    def clear(self) -> None:
        """Clear the panel."""
        self._provider_id = None
        self._ticket = None
        self._show_no_ticket()


class CompactProviderInfo(Static):
    """Compact single-line provider ticket info."""

    DEFAULT_CSS = """
    CompactProviderInfo {
        width: 100%;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, ticket: TicketDetails | None = None, **kwargs):
        """Initialize compact provider info.

        Args:
            ticket: Optional ticket details to display
        """
        if ticket:
            status = ticket.status or "Unknown"
            cached = " (cached)" if ticket.is_cached else ""
            content = f"{ticket.provider_id}: {status}{cached}"
        else:
            content = "No linked ticket"

        super().__init__(content, **kwargs)
