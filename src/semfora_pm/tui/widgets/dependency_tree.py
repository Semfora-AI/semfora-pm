"""Dependency tree widget for visualizing blockers and dependents."""

from textual.app import ComposeResult
from textual.containers import Container, Vertical, ScrollableContainer
from textual.widgets import Static, Tree
from textual.widget import Widget
from textual.message import Message

from ...dependencies import BlockerInfo, Dependency


class DependencySection(Container):
    """A section showing a list of dependencies."""

    DEFAULT_CSS = """
    DependencySection {
        width: 100%;
        height: auto;
        min-height: 5;
        padding: 1;
        margin-bottom: 1;
        border: solid $surface-lighten-1;
    }

    DependencySection .section-header {
        width: 100%;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $surface-lighten-1;
    }

    DependencySection.blocks-section .section-header {
        color: $warning;
    }

    DependencySection.blocked-by-section .section-header {
        color: $error;
    }

    DependencySection.related-section .section-header {
        color: $primary;
    }

    DependencySection .section-content {
        width: 100%;
        height: auto;
        padding-top: 1;
    }

    DependencySection .dep-item {
        width: 100%;
        height: 1;
        padding-left: 2;
    }

    DependencySection .dep-item:hover {
        background: $surface-lighten-1;
    }

    DependencySection .dep-item.selected {
        background: $primary-background;
    }

    DependencySection .dep-item.resolved {
        color: $text-muted;
        text-style: italic;
    }

    DependencySection .empty-message {
        color: $text-muted;
        padding-left: 2;
    }
    """

    class ItemSelected(Message):
        """Message sent when a dependency item is selected."""

        def __init__(self, item_type: str, item_id: str, title: str):
            self.item_type = item_type
            self.item_id = item_id
            self.title = title
            super().__init__()

    def __init__(
        self,
        title: str,
        section_class: str,
        items: list[BlockerInfo],
        **kwargs
    ):
        """Initialize the dependency section.

        Args:
            title: Section title (e.g., "BLOCKS", "BLOCKED BY")
            section_class: CSS class for styling (blocks-section, blocked-by-section, related-section)
            items: List of BlockerInfo items to display
        """
        super().__init__(**kwargs)
        self.section_title = title
        self.items = items
        self.add_class(section_class)
        self.selected_index = -1

    def compose(self) -> ComposeResult:
        """Create the section UI."""
        count = len(self.items)
        yield Static(f"{self.section_title} ({count})", classes="section-header")
        with Container(classes="section-content"):
            if self.items:
                for i, item in enumerate(self.items):
                    yield self._create_item_widget(item, i)
            else:
                yield Static("None", classes="empty-message")

    def _create_item_widget(self, item: BlockerInfo, index: int) -> Static:
        """Create a widget for a dependency item."""
        # Build display string
        resolved_marker = " [done]" if item.resolved else ""
        depth_marker = "  " * (item.depth - 1) if item.depth > 1 else ""

        title = item.title
        if len(title) > 40:
            title = title[:37] + "..."

        text = f"{depth_marker}+-- {title}{resolved_marker}"

        widget = Static(text, classes="dep-item", id=f"dep-{index}")
        widget.item_info = item  # Store for later access

        if item.resolved:
            widget.add_class("resolved")

        return widget

    def update_items(self, items: list[BlockerInfo]) -> None:
        """Update the displayed items."""
        self.items = items

        # Update header
        header = self.query_one(".section-header", Static)
        header.update(f"{self.section_title} ({len(items)})")

        # Update content
        content = self.query_one(".section-content", Container)
        content.remove_children()

        if items:
            for i, item in enumerate(items):
                content.mount(self._create_item_widget(item, i))
        else:
            content.mount(Static("None", classes="empty-message"))

    def select_item(self, index: int) -> None:
        """Select an item by index."""
        # Remove old selection
        for widget in self.query(".dep-item"):
            widget.remove_class("selected")

        # Add new selection
        if 0 <= index < len(self.items):
            self.selected_index = index
            widget = self.query_one(f"#dep-{index}", Static)
            widget.add_class("selected")

    def get_selected_item(self) -> BlockerInfo | None:
        """Get the currently selected item."""
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None


class DependencyTree(Widget):
    """Widget displaying a ticket's full dependency tree."""

    DEFAULT_CSS = """
    DependencyTree {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    DependencyTree .tree-header {
        width: 100%;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    DependencyTree .tree-content {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }

    DependencyTree .no-selection {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding: 2;
    }
    """

    def __init__(
        self,
        ticket_id: str | None = None,
        ticket_title: str | None = None,
        **kwargs
    ):
        """Initialize the dependency tree.

        Args:
            ticket_id: ID of the ticket to show dependencies for
            ticket_title: Title of the ticket
        """
        super().__init__(**kwargs)
        self._ticket_id = ticket_id
        self._ticket_title = ticket_title
        self._blocks: list[BlockerInfo] = []
        self._blocked_by: list[BlockerInfo] = []
        self._related: list[Dependency] = []

    def compose(self) -> ComposeResult:
        """Create the tree UI."""
        if self._ticket_title:
            yield Static(f"Dependencies for: {self._ticket_title}", classes="tree-header")
        else:
            yield Static("Select a ticket to view dependencies", classes="tree-header")

        with ScrollableContainer(classes="tree-content"):
            if self._ticket_id:
                yield DependencySection(
                    "BLOCKS (waiting for this)",
                    "blocks-section",
                    self._blocks,
                    id="blocks-section"
                )
                yield DependencySection(
                    "BLOCKED BY (this waits for)",
                    "blocked-by-section",
                    self._blocked_by,
                    id="blocked-by-section"
                )
            else:
                yield Static("No ticket selected", classes="no-selection")

    def load_dependencies(
        self,
        ticket_id: str = None,
        ticket_title: str = None,
        blocks: list[BlockerInfo] = None,
        blocked_by: list[BlockerInfo] = None,
        # Backward compatibility aliases
        plan_id: str = None,
        plan_title: str = None,
    ) -> None:
        """Load dependencies for a ticket.

        Args:
            ticket_id: ID of the ticket
            ticket_title: Title of the ticket
            blocks: Items that this ticket blocks (dependents)
            blocked_by: Items that block this ticket (blockers)
            plan_id: (deprecated) Alias for ticket_id
            plan_title: (deprecated) Alias for ticket_title
        """
        # Support backward compatibility
        ticket_id = ticket_id or plan_id
        ticket_title = ticket_title or plan_title
        blocks = blocks or []
        blocked_by = blocked_by or []

        self._ticket_id = ticket_id
        self._ticket_title = ticket_title
        self._blocks = blocks
        self._blocked_by = blocked_by

        # Update header
        header = self.query_one(".tree-header", Static)
        title = ticket_title
        if len(title) > 40:
            title = title[:37] + "..."
        header.update(f"Dependencies for: {title}")

        # Update sections
        content = self.query_one(".tree-content", ScrollableContainer)

        # Check if sections exist
        blocks_section = content.query("#blocks-section")
        if blocks_section:
            blocks_section.first().update_items(blocks)
        else:
            content.mount(DependencySection(
                "BLOCKS (waiting for this)",
                "blocks-section",
                blocks,
                id="blocks-section"
            ))

        blocked_by_section = content.query("#blocked-by-section")
        if blocked_by_section:
            blocked_by_section.first().update_items(blocked_by)
        else:
            content.mount(DependencySection(
                "BLOCKED BY (this waits for)",
                "blocked-by-section",
                blocked_by,
                id="blocked-by-section"
            ))

        # Remove no-selection message if present
        no_selection = content.query(".no-selection")
        if no_selection:
            no_selection.first().remove()

    def clear(self) -> None:
        """Clear the tree."""
        self._ticket_id = None
        self._ticket_title = None
        self._blocks = []
        self._blocked_by = []

        header = self.query_one(".tree-header", Static)
        header.update("Select a ticket to view dependencies")

        content = self.query_one(".tree-content", ScrollableContainer)
        content.remove_children()
        content.mount(Static("No ticket selected", classes="no-selection"))
