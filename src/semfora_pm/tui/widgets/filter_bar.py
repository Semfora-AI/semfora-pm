"""Filter bar widget for filtering tickets."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Select, Input
from textual.widget import Widget
from textual.message import Message


class FilterBar(Widget):
    """Widget for filtering tickets by status, priority, and tags."""

    DEFAULT_CSS = """
    FilterBar {
        width: 100%;
        height: 3;
        border-bottom: solid $primary;
        padding: 0 1;
        background: $surface-darken-1;
    }

    FilterBar > Horizontal {
        width: 100%;
        height: 100%;
        align: left middle;
    }

    FilterBar .filter-label {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }

    FilterBar Select {
        width: 18;
        margin-right: 2;
    }

    FilterBar Input {
        width: 20;
    }

    FilterBar .filter-clear {
        width: auto;
        padding: 0 1;
        color: $warning;
    }

    FilterBar .filter-clear:hover {
        text-style: bold;
    }
    """

    class FiltersChanged(Message):
        """Message sent when filters change."""

        def __init__(
            self,
            status: str | None,
            priority: int | None,
            tags: list[str],
            show_completed: bool,
        ):
            self.status = status
            self.priority = priority
            self.tags = tags
            self.show_completed = show_completed
            super().__init__()

    # Status options for the dropdown
    STATUS_OPTIONS = [
        ("All", "all"),
        ("Pending", "pending"),
        ("In Progress", "in_progress"),
        ("Blocked", "blocked"),
        ("Completed", "completed"),
        ("Canceled", "canceled"),
    ]

    # Priority options for the dropdown
    PRIORITY_OPTIONS = [
        ("All", -1),
        ("Urgent", 4),
        ("High", 3),
        ("Medium", 2),
        ("Low", 1),
        ("None", 0),
    ]

    def __init__(
        self,
        status: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        show_completed: bool = False,
        **kwargs
    ):
        """Initialize the filter bar.

        Args:
            status: Initial status filter
            priority: Initial priority filter
            tags: Initial tag filters
            show_completed: Whether to show completed items
        """
        super().__init__(**kwargs)
        self._status = status
        self._priority = priority
        self._tags = tags or []
        self._show_completed = show_completed

    def compose(self) -> ComposeResult:
        """Create the filter bar UI."""
        with Horizontal():
            yield Static("Filters:", classes="filter-label")

            # Status filter
            yield Select(
                self.STATUS_OPTIONS,
                value="all" if self._status is None else self._status,
                id="status-filter",
                prompt="Status",
            )

            # Priority filter
            yield Select(
                self.PRIORITY_OPTIONS,
                value=-1 if self._priority is None else self._priority,
                id="priority-filter",
                prompt="Priority",
            )

            # Tags input
            yield Input(
                placeholder="Tags (comma-sep)",
                value=",".join(self._tags),
                id="tags-filter",
            )

            # Clear button
            yield Static("[C]lear", classes="filter-clear", id="clear-filters")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select changes."""
        self._emit_filters_changed()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes."""
        if event.input.id == "tags-filter":
            self._emit_filters_changed()

    def _emit_filters_changed(self) -> None:
        """Emit the FiltersChanged message with current values."""
        # Get status
        status_select = self.query_one("#status-filter", Select)
        status = status_select.value
        if status == "all" or status == Select.BLANK:
            status = None

        # Get priority
        priority_select = self.query_one("#priority-filter", Select)
        priority = priority_select.value
        if priority == -1 or priority == Select.BLANK:
            priority = None

        # Get tags
        tags_input = self.query_one("#tags-filter", Input)
        tags_text = tags_input.value.strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]

        # Determine if showing completed
        show_completed = status in ("completed", "canceled")

        self.post_message(self.FiltersChanged(
            status=status,
            priority=priority,
            tags=tags,
            show_completed=show_completed,
        ))

    def clear_filters(self) -> None:
        """Clear all filters to defaults."""
        status_select = self.query_one("#status-filter", Select)
        status_select.value = "all"

        priority_select = self.query_one("#priority-filter", Select)
        priority_select.value = -1

        tags_input = self.query_one("#tags-filter", Input)
        tags_input.value = ""

        self._emit_filters_changed()

    def on_click(self, event) -> None:
        """Handle click events."""
        # Check if clear button was clicked
        target = event.widget
        if hasattr(target, "id") and target.id == "clear-filters":
            self.clear_filters()

    @property
    def current_status(self) -> str | None:
        """Get current status filter value."""
        status_select = self.query_one("#status-filter", Select)
        value = status_select.value
        return None if value == "all" or value == Select.BLANK else value

    @property
    def current_priority(self) -> int | None:
        """Get current priority filter value."""
        priority_select = self.query_one("#priority-filter", Select)
        value = priority_select.value
        return None if value == -1 or value == Select.BLANK else value

    @property
    def current_tags(self) -> list[str]:
        """Get current tags filter value."""
        tags_input = self.query_one("#tags-filter", Input)
        tags_text = tags_input.value.strip()
        return [t.strip() for t in tags_text.split(",") if t.strip()]
