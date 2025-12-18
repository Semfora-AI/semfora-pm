"""Local tickets screen with filterable list and detail view."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static, Footer, Header, DataTable
from textual.message import Message

from ...local_tickets import LocalTicket, TicketStatus
from ..widgets import FilterBar, StatusBadge, PriorityBadge, ProviderPanel
from ..state import get_status_icon, get_priority_icon, get_priority_label, truncate_title
from .modals import StatusChangeModal, EditLocalTicketModal, ConfirmDeleteModal


class LocalTicketDetailPanel(Container):
    """Panel showing detailed local ticket information."""

    DEFAULT_CSS = """
    LocalTicketDetailPanel {
        width: 30%;
        min-width: 30;
        max-width: 50;
        height: 100%;
        border-left: solid $primary;
        padding: 1;
        background: $surface;
    }

    LocalTicketDetailPanel.hidden {
        display: none;
    }

    LocalTicketDetailPanel .detail-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    LocalTicketDetailPanel .detail-section {
        width: 100%;
        padding: 1 0;
    }

    LocalTicketDetailPanel .detail-label {
        color: $text-muted;
        width: 100%;
    }

    LocalTicketDetailPanel .detail-value {
        width: 100%;
        padding-left: 1;
    }

    LocalTicketDetailPanel .detail-description {
        width: 100%;
        height: auto;
        max-height: 10;
        padding: 1;
        border: solid $surface-lighten-1;
        margin-top: 1;
    }

    LocalTicketDetailPanel .detail-tags {
        width: 100%;
        color: $secondary;
    }

    LocalTicketDetailPanel .no-selection {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the detail panel."""
        super().__init__(**kwargs)
        self._ticket: LocalTicket | None = None

    def compose(self) -> ComposeResult:
        """Create the panel UI."""
        yield Static("Ticket Details", classes="detail-header")
        yield Static("Select a ticket to view details", classes="no-selection", id="no-selection")
        yield Vertical(id="detail-content")

    def show_ticket(self, ticket: LocalTicket) -> None:
        """Display ticket details."""
        self._ticket = ticket

        no_selection = self.query_one("#no-selection", Static)
        no_selection.display = False

        content = self.query_one("#detail-content", Vertical)
        content.display = True
        content.remove_children()

        # Title
        content.mount(Static("Title:", classes="detail-label"))
        content.mount(Static(ticket.title, classes="detail-value"))

        # Status
        content.mount(Static("Status:", classes="detail-label"))
        status_icon = get_status_icon(ticket.status)
        content.mount(Static(f"{status_icon} {ticket.status}", classes="detail-value"))

        # Priority
        content.mount(Static("Priority:", classes="detail-label"))
        priority_label = get_priority_label(ticket.priority)
        content.mount(Static(f"[{get_priority_icon(ticket.priority)}] {priority_label}", classes="detail-value"))

        # Parent ticket
        if ticket.linked_ticket_id:
            content.mount(Static("Parent Ticket:", classes="detail-label"))
            content.mount(Static(ticket.linked_ticket_id, classes="detail-value"))

        # Tags
        if ticket.tags:
            content.mount(Static("Tags:", classes="detail-label"))
            tags_str = " ".join(f"#{tag}" for tag in ticket.tags)
            content.mount(Static(tags_str, classes="detail-tags"))

        # Description
        if ticket.description:
            content.mount(Static("Description:", classes="detail-label"))
            desc = ticket.description
            if len(desc) > 300:
                desc = desc[:297] + "..."
            content.mount(Static(desc, classes="detail-description"))

        # Timestamps
        content.mount(Static("Created:", classes="detail-label"))
        created = ticket.created_at[:19] if ticket.created_at else "Unknown"
        content.mount(Static(created, classes="detail-value"))

        if ticket.completed_at:
            content.mount(Static("Completed:", classes="detail-label"))
            completed = ticket.completed_at[:19]
            content.mount(Static(completed, classes="detail-value"))

    def clear(self) -> None:
        """Clear the panel."""
        self._ticket = None

        no_selection = self.query_one("#no-selection", Static)
        no_selection.display = True

        content = self.query_one("#detail-content", Vertical)
        content.display = False
        content.remove_children()


class LocalTicketsScreen(Screen):
    """Screen for viewing and managing all local tickets."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("enter", "view_detail", "View", show=True),
        Binding("s", "change_status", "Status", show=True),
        Binding("P", "change_priority", "Priority", show=True),
        Binding("e", "edit_ticket", "Edit", show=True),
        Binding("d", "delete_ticket", "Delete", show=True),
        Binding("l", "link_ticket", "Link", show=False),
        Binding("c", "clear_filters", "Clear Filters", show=True),
        Binding("slash", "focus_filter", "Filter", show=False),
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    DEFAULT_CSS = """
    LocalTicketsScreen {
        background: $surface;
    }

    LocalTicketsScreen .tickets-container {
        width: 100%;
        height: 100%;
    }

    LocalTicketsScreen .main-content {
        width: 1fr;
        height: 100%;
    }

    LocalTicketsScreen .tickets-list {
        width: 100%;
        height: 1fr;
        padding: 1;
    }

    LocalTicketsScreen DataTable {
        width: 100%;
        height: 100%;
    }

    LocalTicketsScreen .content-row {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the tickets screen."""
        super().__init__(**kwargs)
        self._tickets: list[LocalTicket] = []
        self._selected_ticket: LocalTicket | None = None

    def compose(self) -> ComposeResult:
        """Create the tickets screen UI."""
        yield Header()
        with Container(classes="tickets-container"):
            # Filter bar at top
            yield FilterBar(id="filter-bar")

            # Main content area with list and detail panel
            with Horizontal(classes="content-row"):
                # Tickets list (DataTable)
                with Container(classes="main-content"):
                    with Container(classes="tickets-list"):
                        table = DataTable(id="tickets-table")
                        table.cursor_type = "row"
                        yield table

                # Detail panel on the right
                yield LocalTicketDetailPanel(id="detail-panel")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize when mounted."""
        # Setup table columns
        table = self.query_one("#tickets-table", DataTable)
        table.add_columns("Status", "Title", "Priority", "Parent", "Tags")

        # Load initial data
        self._refresh_data()

    def _refresh_data(
        self,
        status: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        show_completed: bool = False,
    ) -> None:
        """Refresh the tickets data with optional filters."""
        app = self.app

        # Get tickets with filters
        self._tickets = app.ticket_manager.list(
            status=status,
            tags=tags,
            include_completed=show_completed,
        )

        # Filter by priority client-side (not supported in LocalTicketManager.list)
        if priority is not None:
            self._tickets = [t for t in self._tickets if t.priority == priority]

        # Update table
        self._update_table()

    def _update_table(self) -> None:
        """Update the DataTable with current tickets."""
        table = self.query_one("#tickets-table", DataTable)
        table.clear()

        for ticket in self._tickets:
            status_icon = get_status_icon(ticket.status)
            priority_icon = get_priority_icon(ticket.priority)

            # Truncate title using shared constant
            title = truncate_title(ticket.title)

            # Format parent ticket
            parent = ticket.linked_ticket_id or "-"

            # Format tags
            tags = " ".join(f"#{t}" for t in ticket.tags[:2]) if ticket.tags else "-"

            table.add_row(
                status_icon,
                title,
                f"[{priority_icon}]",
                parent,
                tags,
                key=ticket.id,
            )

        # Select first row if any
        if self._tickets:
            table.move_cursor(row=0)
            self._on_ticket_selected(self._tickets[0])

    def _on_ticket_selected(self, ticket: LocalTicket) -> None:
        """Handle ticket selection."""
        self._selected_ticket = ticket
        detail_panel = self.query_one("#detail-panel", LocalTicketDetailPanel)
        detail_panel.show_ticket(ticket)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (cursor movement).

        Note: We use RowHighlighted (not RowSelected) to update the detail panel
        as the user navigates, providing preview-as-you-browse behavior.
        This avoids duplicate updates that cause thrashing.
        """
        if event.row_key:
            ticket_id = str(event.row_key.value)
            ticket = next((t for t in self._tickets if t.id == ticket_id), None)
            if ticket:
                self._on_ticket_selected(ticket)

    def on_filter_bar_filters_changed(self, event: FilterBar.FiltersChanged) -> None:
        """Handle filter changes."""
        self._refresh_data(
            status=event.status,
            priority=event.priority,
            tags=event.tags,
            show_completed=event.show_completed,
        )

    def action_cursor_down(self) -> None:
        """Move cursor down."""
        table = self.query_one("#tickets-table", DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up."""
        table = self.query_one("#tickets-table", DataTable)
        table.action_cursor_up()

    def action_view_detail(self) -> None:
        """View full ticket details."""
        if self._selected_ticket:
            self.notify(f"Full view: {self._selected_ticket.title[:30]}...")
            # TODO: Push full detail screen or modal

    def action_change_status(self) -> None:
        """Change the status of the selected ticket."""
        if not self._selected_ticket:
            return

        ticket = self._selected_ticket

        def on_status_changed(new_status):
            if new_status:
                # Refresh
                filter_bar = self.query_one("#filter-bar", FilterBar)
                self._refresh_data(
                    status=filter_bar.current_status,
                    priority=filter_bar.current_priority,
                    tags=filter_bar.current_tags,
                )
                self.notify(f"Status changed to: {new_status}")

        self.app.push_screen(StatusChangeModal(ticket), on_status_changed)

    def action_change_priority(self) -> None:
        """Change the priority of the selected ticket."""
        if not self._selected_ticket:
            return

        ticket = self._selected_ticket

        # Cycle through priorities (4 -> 3 -> 2 -> 1 -> 0 -> 4)
        new_priority = (ticket.priority - 1) % 5
        if new_priority < 0:
            new_priority = 4

        self.app.ticket_manager.update(ticket.id, priority=new_priority)

        # Refresh
        filter_bar = self.query_one("#filter-bar", FilterBar)
        self._refresh_data(
            status=filter_bar.current_status,
            priority=filter_bar.current_priority,
            tags=filter_bar.current_tags,
        )

        self.notify(f"Priority: {get_priority_label(ticket.priority)} -> {get_priority_label(new_priority)}")

    def action_edit_ticket(self) -> None:
        """Edit the selected ticket."""
        if not self._selected_ticket:
            return

        ticket = self._selected_ticket

        def on_ticket_updated(updated_ticket):
            if updated_ticket:
                # Refresh
                filter_bar = self.query_one("#filter-bar", FilterBar)
                self._refresh_data(
                    status=filter_bar.current_status,
                    priority=filter_bar.current_priority,
                    tags=filter_bar.current_tags,
                )
                self.notify(f"Updated: {updated_ticket.title[:30]}...")

        self.app.push_screen(EditLocalTicketModal(ticket), on_ticket_updated)

    def action_delete_ticket(self) -> None:
        """Delete the selected ticket."""
        if not self._selected_ticket:
            return

        ticket = self._selected_ticket

        def on_delete_confirmed(deleted):
            if deleted:
                # Refresh
                filter_bar = self.query_one("#filter-bar", FilterBar)
                self._refresh_data(
                    status=filter_bar.current_status,
                    priority=filter_bar.current_priority,
                    tags=filter_bar.current_tags,
                )
                self.notify(f"Deleted: {ticket.title[:30]}...")

        self.app.push_screen(ConfirmDeleteModal(ticket), on_delete_confirmed)

    def action_link_ticket(self) -> None:
        """Link a parent ticket to the selected local ticket."""
        if self._selected_ticket:
            self.notify("Link ticket modal not yet implemented")
            # TODO: Show ticket search/link modal

    def action_clear_filters(self) -> None:
        """Clear all filters."""
        filter_bar = self.query_one("#filter-bar", FilterBar)
        filter_bar.clear_filters()

    def action_focus_filter(self) -> None:
        """Focus the filter bar."""
        filter_bar = self.query_one("#filter-bar", FilterBar)
        filter_bar.focus()
