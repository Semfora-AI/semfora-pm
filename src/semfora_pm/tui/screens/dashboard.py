"""Dashboard screen with status columns."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static, Footer, Header
from textual.message import Message

from ...local_tickets import LocalTicket, TicketStatus
from ...dependencies import ReadyWorkItem
from ..widgets import StatusBadge, PriorityBadge, CompactLocalTicketItem
from ..state import truncate_title, TITLE_TRUNCATE_LENGTH


class TicketEntry(Container):
    """A simple container for ticket entries with title and meta lines."""

    def __init__(self, title_line: str, meta_line: str, ticket_id: str, **kwargs):
        super().__init__(classes="ticket-entry", id=f"ticket-{ticket_id[:8]}", **kwargs)
        self._title_line = title_line
        self._meta_line = meta_line

    def compose(self) -> ComposeResult:
        yield Static(self._title_line, classes="ticket-title")
        yield Static(self._meta_line, classes="ticket-meta")


class StatusColumn(Container):
    """A column displaying tickets with a specific status."""

    DEFAULT_CSS = """
    StatusColumn {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        margin: 0 1;
    }

    StatusColumn .column-header {
        width: 100%;
        height: 3;
        text-align: center;
        text-style: bold;
        border-bottom: solid $primary;
        padding: 0 1;
        background: $surface-darken-1;
    }

    StatusColumn .column-header .count {
        color: $text-muted;
    }

    StatusColumn .column-content {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        padding: 1;
    }

    StatusColumn .ticket-entry {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        border-bottom: dashed $surface-lighten-1;
        margin-bottom: 1;
    }

    StatusColumn .ticket-entry:hover {
        background: $surface-lighten-1;
    }

    StatusColumn .ticket-entry.selected {
        background: $primary-background;
        border-left: thick $primary;
        padding-left: 1;
    }

    StatusColumn .ticket-title {
        width: 100%;
    }

    StatusColumn .ticket-meta {
        width: 100%;
        color: $text-muted;
        height: 1;
    }

    StatusColumn .empty-message {
        color: $text-muted;
        text-align: center;
        padding: 2;
    }
    """

    class TicketSelected(Message):
        """Message sent when a ticket is selected in a column."""

        def __init__(self, ticket: LocalTicket, column_status: str):
            self.ticket = ticket
            self.column_status = column_status
            super().__init__()

    def __init__(
        self,
        status: str,
        title: str,
        tickets: list[LocalTicket],
        is_blocked_column: bool = False,
        **kwargs
    ):
        """Initialize a status column.

        Args:
            status: The status filter for this column
            title: Display title for the column
            tickets: List of tickets to display
            is_blocked_column: Whether this is the blocked column (special handling)
        """
        super().__init__(**kwargs)
        self.column_status = status
        self.column_title = title
        self.tickets = tickets
        self.is_blocked_column = is_blocked_column
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        """Create the column UI."""
        count = len(self.tickets)
        yield Static(
            f"{self.column_title} [dim]({count})[/dim]",
            classes="column-header"
        )
        with ScrollableContainer(classes="column-content"):
            if self.tickets:
                for ticket in self.tickets:
                    yield self._create_ticket_entry(ticket)
            else:
                yield Static("No tickets", classes="empty-message")

    def _create_ticket_entry(self, ticket: LocalTicket) -> "TicketEntry":
        """Create a container for a ticket entry."""
        from ..state import get_status_icon, get_priority_icon

        status_icon = get_status_icon(ticket.status)
        priority_icon = get_priority_icon(ticket.priority)

        title_text = truncate_title(ticket.title)

        # Build meta line
        meta_parts = [f"[{priority_icon}]"]
        if ticket.linked_ticket_id:
            meta_parts.append(ticket.linked_ticket_id)

        return TicketEntry(
            title_line=f"{status_icon} {title_text}",
            meta_line=" ".join(meta_parts),
            ticket_id=ticket.id,
        )

    def update_tickets(self, tickets: list[LocalTicket]) -> None:
        """Update the displayed tickets."""
        self.tickets = tickets
        content = self.query_one(".column-content", ScrollableContainer)
        content.remove_children()

        # Update header count
        header = self.query_one(".column-header", Static)
        header.update(f"{self.column_title} [dim]({len(tickets)})[/dim]")

        if tickets:
            for ticket in tickets:
                content.mount(self._create_ticket_entry(ticket))
        else:
            content.mount(Static("No tickets", classes="empty-message"))

    def select_ticket(self, index: int) -> None:
        """Select a ticket by index."""
        if not self.tickets:
            return

        # Clamp index
        index = max(0, min(index, len(self.tickets) - 1))

        # Remove old selection
        for entry in self.query(".ticket-entry"):
            entry.remove_class("selected")

        # Add new selection
        self.selected_index = index
        if index < len(self.tickets):
            ticket_id = self.tickets[index].id[:8]
            entry = self.query_one(f"#ticket-{ticket_id}", Container)
            entry.add_class("selected")

    def get_selected_ticket(self) -> LocalTicket | None:
        """Get the currently selected ticket."""
        if self.tickets and 0 <= self.selected_index < len(self.tickets):
            return self.tickets[self.selected_index]
        return None


class ReadyWorkPanel(Container):
    """Panel showing items ready to work on."""

    DEFAULT_CSS = """
    ReadyWorkPanel {
        width: 100%;
        height: auto;
        min-height: 5;
        max-height: 10;
        border-top: solid $success;
        padding: 1;
        background: $surface-darken-1;
    }

    ReadyWorkPanel .panel-header {
        width: 100%;
        text-style: bold;
        color: $success;
        padding-bottom: 1;
    }

    ReadyWorkPanel .ready-items {
        width: 100%;
        height: auto;
    }

    ReadyWorkPanel .ready-item {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    ReadyWorkPanel .ready-item:hover {
        background: $surface-lighten-1;
    }

    ReadyWorkPanel .empty-message {
        color: $text-muted;
    }
    """

    def __init__(self, items: list[ReadyWorkItem], **kwargs):
        """Initialize the ready work panel.

        Args:
            items: List of ready work items to display
        """
        super().__init__(**kwargs)
        self.items = items

    def compose(self) -> ComposeResult:
        """Create the panel UI."""
        yield Static(
            f"Ready to Work ({len(self.items)})",
            classes="panel-header"
        )
        with Container(classes="ready-items"):
            if self.items:
                for item in self.items:
                    yield self._create_ready_item(item)
            else:
                yield Static("All items have blockers", classes="empty-message")

    def _create_ready_item(self, item: ReadyWorkItem) -> Static:
        """Create a ready item display."""
        from ..state import get_priority_icon

        priority_icon = get_priority_icon(item.priority)
        ticket = f" ({item.linked_ticket_id})" if item.linked_ticket_id else ""

        title = truncate_title(item.title, 50)

        return Static(
            f"[{priority_icon}] {title}{ticket}",
            classes="ready-item"
        )

    def update_items(self, items: list[ReadyWorkItem]) -> None:
        """Update the displayed items."""
        self.items = items

        header = self.query_one(".panel-header", Static)
        header.update(f"Ready to Work ({len(items)})")

        items_container = self.query_one(".ready-items", Container)
        items_container.remove_children()

        if items:
            for item in items:
                items_container.mount(self._create_ready_item(item))
        else:
            items_container.mount(
                Static("All items have blockers", classes="empty-message")
            )


class DashboardScreen(Screen):
    """Main dashboard screen with status columns."""

    BINDINGS = [
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("tab", "next_column", "Next Column", show=True),
        Binding("shift+tab", "prev_column", "Prev Column", show=False),
        Binding("enter", "view_ticket", "View", show=True),
        Binding("s", "cycle_status", "Status", show=True),
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        background: $surface;
    }

    DashboardScreen .dashboard-container {
        width: 100%;
        height: 100%;
    }

    DashboardScreen .columns-row {
        width: 100%;
        height: 1fr;
        padding: 1;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the dashboard screen."""
        super().__init__(**kwargs)
        self.active_column = 0  # 0=in_progress, 1=todo, 2=blocked
        self.columns: list[StatusColumn] = []

    def compose(self) -> ComposeResult:
        """Create the dashboard UI."""
        yield Header()
        with Container(classes="dashboard-container"):
            with Horizontal(classes="columns-row"):
                # In Progress column
                yield StatusColumn(
                    status="in_progress",
                    title="In Progress",
                    tickets=[],
                    id="col-in-progress"
                )
                # Todo column
                yield StatusColumn(
                    status="pending",
                    title="Todo",
                    tickets=[],
                    id="col-todo"
                )
                # Blocked column
                yield StatusColumn(
                    status="blocked",
                    title="Blocked",
                    tickets=[],
                    is_blocked_column=True,
                    id="col-blocked"
                )
            # Ready work panel at bottom
            yield ReadyWorkPanel(items=[], id="ready-panel")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize when mounted."""
        self.columns = [
            self.query_one("#col-in-progress", StatusColumn),
            self.query_one("#col-todo", StatusColumn),
            self.query_one("#col-blocked", StatusColumn),
        ]
        self._refresh_data()
        self._update_column_focus()

    def _refresh_data(self) -> None:
        """Refresh data from the database."""
        app = self.app

        # Get tickets by status
        all_tickets = app.ticket_manager.list(include_completed=False)

        in_progress = [t for t in all_tickets if t.status == "in_progress"]
        todo = [t for t in all_tickets if t.status == "pending"]
        blocked = [t for t in all_tickets if t.status == "blocked"]

        # Update columns
        self.columns[0].update_tickets(in_progress)
        self.columns[1].update_tickets(todo)
        self.columns[2].update_tickets(blocked)

        # Update ready work panel
        ready_items = app.dep_manager.get_ready_work(include_local=True, limit=5)
        ready_panel = self.query_one("#ready-panel", ReadyWorkPanel)
        ready_panel.update_items(ready_items)

    def _update_column_focus(self) -> None:
        """Update visual focus indicator for active column."""
        for i, col in enumerate(self.columns):
            if i == self.active_column:
                col.styles.border = ("solid", "green")
            else:
                col.styles.border = ("solid", "gray")

    def action_move_down(self) -> None:
        """Move selection down in current column."""
        col = self.columns[self.active_column]
        col.select_ticket(col.selected_index + 1)

    def action_move_up(self) -> None:
        """Move selection up in current column."""
        col = self.columns[self.active_column]
        col.select_ticket(col.selected_index - 1)

    def action_next_column(self) -> None:
        """Move to next column."""
        self.active_column = (self.active_column + 1) % 3
        self._update_column_focus()

    def action_prev_column(self) -> None:
        """Move to previous column."""
        self.active_column = (self.active_column - 1) % 3
        self._update_column_focus()

    def action_view_ticket(self) -> None:
        """View the selected ticket details."""
        col = self.columns[self.active_column]
        ticket = col.get_selected_ticket()
        if ticket:
            self.notify(f"Viewing: {ticket.title[:40]}...")
            # TODO: Push ticket detail screen

    def action_cycle_status(self) -> None:
        """Cycle the status of the selected ticket."""
        col = self.columns[self.active_column]
        ticket = col.get_selected_ticket()
        if not ticket:
            return

        # Define status cycle
        status_cycle = {
            "pending": "in_progress",
            "in_progress": "completed",
            "blocked": "pending",
        }

        new_status = status_cycle.get(ticket.status)
        if new_status:
            self.app.ticket_manager.update(ticket.id, status=new_status)
            self._refresh_data()
            self.notify(f"Status: {ticket.status} → {new_status}")
