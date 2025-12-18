"""Status and priority badge widgets."""

from textual.widgets import Static

from ..state import (
    STATUS_DISPLAY,
    PRIORITY_DISPLAY,
    get_status_icon,
    get_status_class,
    get_priority_icon,
    get_priority_class,
)


class StatusBadge(Static):
    """Widget displaying a plan's status with icon and color."""

    DEFAULT_CSS = """
    StatusBadge {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, status: str, show_label: bool = False, **kwargs):
        """Initialize the status badge.

        Args:
            status: The plan status (pending, in_progress, completed, etc.)
            show_label: If True, show full label; if False, show icon only
        """
        self.status = status
        self.show_label = show_label

        icon = get_status_icon(status)
        css_class = get_status_class(status)

        if show_label:
            label = status.replace("_", " ").title()
            content = f"{icon} {label}"
        else:
            content = icon

        super().__init__(content, **kwargs)
        self.add_class(css_class)

    def update_status(self, status: str) -> None:
        """Update the displayed status."""
        # Remove old class
        old_class = get_status_class(self.status)
        self.remove_class(old_class)

        # Update to new status
        self.status = status
        icon = get_status_icon(status)
        css_class = get_status_class(status)

        if self.show_label:
            label = status.replace("_", " ").title()
            self.update(f"{icon} {label}")
        else:
            self.update(icon)

        self.add_class(css_class)


class PriorityBadge(Static):
    """Widget displaying a plan's priority with icon and color."""

    DEFAULT_CSS = """
    PriorityBadge {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, priority: int, show_label: bool = False, **kwargs):
        """Initialize the priority badge.

        Args:
            priority: The priority level (0-4, higher = more important)
            show_label: If True, show full label; if False, show icon only
        """
        self.priority = priority
        self.show_label = show_label

        icon = get_priority_icon(priority)
        css_class = get_priority_class(priority)

        if show_label:
            label = PRIORITY_DISPLAY.get(priority, ("", "", "None"))[2]
            content = f"[{icon}] {label}"
        else:
            content = f"[{icon}]"

        super().__init__(content, **kwargs)
        self.add_class(css_class)

    def update_priority(self, priority: int) -> None:
        """Update the displayed priority."""
        # Remove old class
        old_class = get_priority_class(self.priority)
        self.remove_class(old_class)

        # Update to new priority
        self.priority = priority
        icon = get_priority_icon(priority)
        css_class = get_priority_class(priority)

        if self.show_label:
            label = PRIORITY_DISPLAY.get(priority, ("", "", "None"))[2]
            self.update(f"[{icon}] {label}")
        else:
            self.update(f"[{icon}]")

        self.add_class(css_class)
