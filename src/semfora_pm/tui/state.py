"""Application state management for the TUI."""

from dataclasses import dataclass, field
from typing import Optional

from ..local_tickets import LocalTicket, TicketStatus
from ..dependencies import ReadyWorkItem


# Shared UI constants
TITLE_TRUNCATE_LENGTH = 40  # Standard truncation length for titles
TITLE_TRUNCATE_SHORT = 25   # For narrow panels like selectors


@dataclass
class AppState:
    """Central application state for the TUI.

    This dataclass holds all UI state that needs to be shared
    across screens and widgets.
    """

    # Current selections
    selected_ticket_id: Optional[str] = None
    selected_tickets: set[str] = field(default_factory=set)

    # Filter state
    status_filter: Optional[TicketStatus] = None
    priority_filter: Optional[int] = None
    tag_filter: list[str] = field(default_factory=list)

    # UI state
    current_screen: str = "dashboard"
    show_completed: bool = False
    show_help: bool = False

    # Cached data (refreshed on demand)
    tickets_cache: list[LocalTicket] = field(default_factory=list)
    ready_work_cache: list[ReadyWorkItem] = field(default_factory=list)

    def clear_filters(self) -> None:
        """Reset all filters to default."""
        self.status_filter = None
        self.priority_filter = None
        self.tag_filter = []

    def clear_selection(self) -> None:
        """Clear current selection."""
        self.selected_ticket_id = None
        self.selected_tickets.clear()

    def toggle_ticket_selection(self, ticket_id: str) -> None:
        """Toggle a ticket in the multi-select set."""
        if ticket_id in self.selected_tickets:
            self.selected_tickets.discard(ticket_id)
        else:
            self.selected_tickets.add(ticket_id)


# Status display mapping
STATUS_DISPLAY = {
    "pending": ("[ ]", "badge-pending"),
    "in_progress": ("[>]", "badge-progress"),
    "completed": ("[x]", "badge-complete"),
    "blocked": ("[!]", "badge-blocked"),
    "canceled": ("[-]", "badge-canceled"),
    "orphaned": ("[?]", "badge-orphaned"),
}

# Priority display mapping (0-4 scale, higher = more important)
PRIORITY_DISPLAY = {
    4: ("U", "priority-urgent", "Urgent"),
    3: ("H", "priority-high", "High"),
    2: ("M", "priority-medium", "Medium"),
    1: ("L", "priority-low", "Low"),
    0: ("-", "priority-none", "None"),
}


def get_status_icon(status: str) -> str:
    """Get the icon for a status."""
    return STATUS_DISPLAY.get(status, ("[ ]", ""))[0]


def get_status_class(status: str) -> str:
    """Get the CSS class for a status."""
    return STATUS_DISPLAY.get(status, ("", "badge-pending"))[1]


def get_priority_icon(priority: int) -> str:
    """Get the icon for a priority level."""
    return PRIORITY_DISPLAY.get(priority, ("-", "", ""))[0]


def get_priority_class(priority: int) -> str:
    """Get the CSS class for a priority level."""
    return PRIORITY_DISPLAY.get(priority, ("", "priority-none", ""))[1]


def get_priority_label(priority: int) -> str:
    """Get the label for a priority level."""
    return PRIORITY_DISPLAY.get(priority, ("", "", "None"))[2]


def truncate_title(title: str, length: int = TITLE_TRUNCATE_LENGTH) -> str:
    """Truncate a title to the specified length with ellipsis.

    Args:
        title: The title to truncate
        length: Maximum length (default: TITLE_TRUNCATE_LENGTH)

    Returns:
        Truncated title with "..." if it exceeds length
    """
    if len(title) <= length:
        return title
    return title[:length - 3] + "..."
