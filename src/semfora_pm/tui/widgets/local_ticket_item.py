"""Local ticket item widget for displaying a single ticket."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static
from textual.widget import Widget
from textual.message import Message

from ...local_tickets import LocalTicket
from .status_badge import StatusBadge, PriorityBadge


class LocalTicketItem(Widget):
    """Widget displaying a single local ticket with status, title, and priority."""

    DEFAULT_CSS = """
    LocalTicketItem {
        width: 100%;
        height: 3;
        padding: 0 1;
        border-bottom: solid $surface-lighten-1;
    }

    LocalTicketItem:hover {
        background: $surface-lighten-1;
    }

    LocalTicketItem.selected {
        background: $primary-background;
        border-left: thick $primary;
    }

    LocalTicketItem.blocked {
        opacity: 0.7;
    }

    LocalTicketItem > Horizontal {
        width: 100%;
        height: 100%;
        align: left middle;
    }

    LocalTicketItem .ticket-title {
        width: 1fr;
        padding: 0 1;
    }

    LocalTicketItem .ticket-parent {
        width: auto;
        color: $text-muted;
        padding: 0 1;
    }

    LocalTicketItem .ticket-tags {
        width: auto;
        color: $secondary;
        padding: 0 1;
    }
    """

    class Selected(Message):
        """Message sent when ticket is selected."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    class StatusChanged(Message):
        """Message sent when status change is requested."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    class PriorityChanged(Message):
        """Message sent when priority change is requested."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    def __init__(
        self,
        ticket: LocalTicket,
        show_parent: bool = True,
        show_tags: bool = False,
        is_blocked: bool = False,
        **kwargs,
    ):
        """Initialize the ticket item.

        Args:
            ticket: The LocalTicket to display
            show_parent: Whether to show parent ticket ID
            show_tags: Whether to show tags
            is_blocked: Whether this ticket is blocked by dependencies
        """
        super().__init__(**kwargs)
        self.ticket = ticket
        self.show_parent = show_parent
        self.show_tags = show_tags
        self._is_blocked = is_blocked

        if is_blocked:
            self.add_class("blocked")

    def compose(self) -> ComposeResult:
        """Create the ticket item UI."""
        with Horizontal():
            yield StatusBadge(self.ticket.status)
            yield Static(self.ticket.title, classes="ticket-title")
            yield PriorityBadge(self.ticket.priority)

            if self.show_parent and self.ticket.linked_ticket_id:
                yield Static(self.ticket.linked_ticket_id, classes="ticket-parent")

            if self.show_tags and self.ticket.tags:
                tags_str = " ".join(f"#{tag}" for tag in self.ticket.tags[:3])
                yield Static(tags_str, classes="ticket-tags")

    def on_click(self) -> None:
        """Handle click events."""
        self.post_message(self.Selected(self.ticket))

    def toggle_selected(self, selected: bool) -> None:
        """Toggle the selected state."""
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def update_ticket(self, ticket: LocalTicket) -> None:
        """Update the displayed ticket."""
        self.ticket = ticket

        # Update status badge
        status_badge = self.query_one(StatusBadge)
        status_badge.update_status(ticket.status)

        # Update priority badge
        priority_badge = self.query_one(PriorityBadge)
        priority_badge.update_priority(ticket.priority)

        # Update title
        title_widget = self.query_one(".ticket-title", Static)
        title_widget.update(ticket.title)

        # Update parent if shown
        if self.show_parent:
            parent_widget = self.query(".ticket-parent", Static)
            if parent_widget:
                parent_widget.first().update(ticket.linked_ticket_id or "")


class CompactLocalTicketItem(Static):
    """Compact single-line ticket display for lists."""

    DEFAULT_CSS = """
    CompactLocalTicketItem {
        width: 100%;
        height: 1;
        padding: 0 1;
    }

    CompactLocalTicketItem:hover {
        background: $surface-lighten-1;
    }

    CompactLocalTicketItem.selected {
        background: $primary-background;
    }
    """

    def __init__(self, ticket: LocalTicket, max_title_len: int = 40, **kwargs):
        """Initialize compact ticket item.

        Args:
            ticket: The LocalTicket to display
            max_title_len: Maximum title length before truncation
        """
        self.ticket = ticket

        # Build compact display string
        from ..state import get_status_icon, get_priority_icon

        status_icon = get_status_icon(ticket.status)
        priority_icon = get_priority_icon(ticket.priority)

        title = ticket.title
        if len(title) > max_title_len:
            title = title[: max_title_len - 3] + "..."

        parent = f" ({ticket.linked_ticket_id})" if ticket.linked_ticket_id else ""

        content = f"{status_icon} [{priority_icon}] {title}{parent}"

        super().__init__(content, **kwargs)
