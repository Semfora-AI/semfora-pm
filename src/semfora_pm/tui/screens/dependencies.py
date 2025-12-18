"""Dependencies screen with tree visualization."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Static, Footer, Header, ListItem, ListView
from textual.message import Message

from ...local_tickets import LocalTicket
from ...dependencies import BlockerInfo, Dependency
from ..widgets import DependencyTree, DependencySection
from ..state import get_status_icon, get_priority_icon, truncate_title, TITLE_TRUNCATE_SHORT


class TicketListItem(Container):
    """A list item for displaying a ticket in the selector."""

    def __init__(self, label: str, ticket: LocalTicket, index: int, selected: bool = False, **kwargs):
        classes = "ticket-list-item"
        if selected:
            classes += " selected"
        super().__init__(classes=classes, id=f"ticket-item-{index}", **kwargs)
        self._label = label
        self.ticket = ticket

    def compose(self) -> ComposeResult:
        yield Static(self._label)


class TicketSelector(Container):
    """Left panel for selecting a ticket to view dependencies."""

    DEFAULT_CSS = """
    TicketSelector {
        width: 25%;
        min-width: 25;
        max-width: 40;
        height: 100%;
        border-right: solid $primary;
        padding: 1;
    }

    TicketSelector .selector-header {
        width: 100%;
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    TicketSelector .ticket-list {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }

    TicketSelector .ticket-list-item {
        width: 100%;
        height: 2;
        padding: 0 1;
    }

    TicketSelector .ticket-list-item:hover {
        background: $surface-lighten-1;
    }

    TicketSelector .ticket-list-item.selected {
        background: $primary-background;
        border-left: thick $primary;
    }
    """

    class TicketSelected(Message):
        """Message sent when a ticket is selected."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    def __init__(self, tickets: list[LocalTicket], **kwargs):
        """Initialize the ticket selector.

        Args:
            tickets: List of tickets to display
        """
        super().__init__(**kwargs)
        self.tickets = tickets
        self.selected_index = 0

    def compose(self) -> ComposeResult:
        """Create the selector UI."""
        yield Static("Select Ticket", classes="selector-header")
        with ScrollableContainer(classes="ticket-list"):
            for i, ticket in enumerate(self.tickets):
                yield self._create_ticket_item(ticket, i)

    def _create_ticket_item(self, ticket: LocalTicket, index: int) -> TicketListItem:
        """Create a ticket item widget."""
        status_icon = get_status_icon(ticket.status)
        priority_icon = get_priority_icon(ticket.priority)

        title = truncate_title(ticket.title, TITLE_TRUNCATE_SHORT)

        label = f"{status_icon} [{priority_icon}] {title}"
        return TicketListItem(label=label, ticket=ticket, index=index, selected=(index == 0))

    def update_tickets(self, tickets: list[LocalTicket]) -> None:
        """Update the list of tickets."""
        self.tickets = tickets
        self.selected_index = 0

        ticket_list = self.query_one(".ticket-list", ScrollableContainer)
        ticket_list.remove_children()

        for i, ticket in enumerate(tickets):
            ticket_list.mount(self._create_ticket_item(ticket, i))

        # Select first item
        if tickets:
            self._update_selection(0)

    def select_next(self) -> None:
        """Select the next ticket."""
        if self.tickets and self.selected_index < len(self.tickets) - 1:
            self._update_selection(self.selected_index + 1)

    def select_prev(self) -> None:
        """Select the previous ticket."""
        if self.tickets and self.selected_index > 0:
            self._update_selection(self.selected_index - 1)

    def _update_selection(self, new_index: int) -> None:
        """Update the selection to a new index."""
        # Remove old selection
        for item in self.query(".ticket-list-item"):
            item.remove_class("selected")

        # Add new selection
        self.selected_index = new_index
        item = self.query_one(f"#ticket-item-{new_index}", Container)
        item.add_class("selected")

        # Emit message
        if 0 <= new_index < len(self.tickets):
            self.post_message(self.TicketSelected(self.tickets[new_index]))

    def get_selected_ticket(self) -> LocalTicket | None:
        """Get the currently selected ticket."""
        if 0 <= self.selected_index < len(self.tickets):
            return self.tickets[self.selected_index]
        return None

    def on_click(self, event) -> None:
        """Handle click events on ticket items."""
        # Find clicked ticket item
        target = event.widget
        while target and not hasattr(target, "ticket"):
            target = target.parent

        if target and hasattr(target, "ticket"):
            # Find index
            for i, ticket in enumerate(self.tickets):
                if ticket.id == target.ticket.id:
                    self._update_selection(i)
                    break


class DependenciesScreen(Screen):
    """Screen for viewing and managing ticket dependencies."""

    BINDINGS = [
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("tab", "switch_panel", "Switch", show=True),
        # TODO: These features are not yet implemented - hidden until ready
        Binding("enter", "jump_to_item", "Jump", show=False),
        Binding("a", "add_dependency", "Add Dep", show=False),
        Binding("r", "remove_dependency", "Remove", show=False),
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    DEFAULT_CSS = """
    DependenciesScreen {
        background: $surface;
    }

    DependenciesScreen .deps-container {
        width: 100%;
        height: 100%;
    }

    DependenciesScreen .main-row {
        width: 100%;
        height: 1fr;
    }

    DependenciesScreen .tree-panel {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    DependenciesScreen .active-panel {
        border: solid $success;
    }

    DependenciesScreen .inactive-panel {
        border: solid $surface-lighten-1;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the dependencies screen."""
        super().__init__(**kwargs)
        self._tickets: list[LocalTicket] = []
        self._selected_ticket: LocalTicket | None = None
        self._active_panel = 0  # 0 = selector, 1 = tree

    def compose(self) -> ComposeResult:
        """Create the dependencies screen UI."""
        yield Header()
        with Container(classes="deps-container"):
            with Horizontal(classes="main-row"):
                yield TicketSelector(tickets=[], id="ticket-selector")
                with Container(classes="tree-panel", id="tree-panel"):
                    yield DependencyTree(id="dep-tree")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize when mounted."""
        self._refresh_data()
        self._update_panel_focus()

    def _refresh_data(self) -> None:
        """Refresh data from the database."""
        app = self.app

        # Get all non-completed tickets
        self._tickets = app.ticket_manager.list(include_completed=False)

        # Update selector
        selector = self.query_one("#ticket-selector", TicketSelector)
        selector.update_tickets(self._tickets)

        # Load dependencies for first ticket
        if self._tickets:
            self._load_dependencies(self._tickets[0])

    def _load_dependencies(self, ticket: LocalTicket) -> None:
        """Load dependencies for a ticket."""
        self._selected_ticket = ticket
        app = self.app

        # Get blockers (items that block this ticket)
        blocked_by = app.dep_manager.get_blockers(
            ticket.id,
            item_type="local",
            recursive=True,
            include_resolved=True,
        )

        # Get dependents (items that this ticket blocks)
        blocks = app.dep_manager.get_dependents(
            ticket.id,
            item_type="local",
            recursive=True,
        )

        # Update tree
        tree = self.query_one("#dep-tree", DependencyTree)
        tree.load_dependencies(
            plan_id=ticket.id,
            plan_title=ticket.title,
            blocks=blocks,
            blocked_by=blocked_by,
        )

    def _update_panel_focus(self) -> None:
        """Update visual focus indicators."""
        selector = self.query_one("#ticket-selector", TicketSelector)
        tree_panel = self.query_one("#tree-panel", Container)

        selector.remove_class("active-panel", "inactive-panel")
        tree_panel.remove_class("active-panel", "inactive-panel")

        if self._active_panel == 0:
            selector.add_class("active-panel")
            tree_panel.add_class("inactive-panel")
        else:
            selector.add_class("inactive-panel")
            tree_panel.add_class("active-panel")

    def on_ticket_selector_ticket_selected(self, event: TicketSelector.TicketSelected) -> None:
        """Handle ticket selection from selector."""
        self._load_dependencies(event.ticket)

    def action_move_down(self) -> None:
        """Move selection down."""
        if self._active_panel == 0:
            selector = self.query_one("#ticket-selector", TicketSelector)
            selector.select_next()
        else:
            # Navigate within tree sections
            self.notify("Tree navigation not fully implemented")

    def action_move_up(self) -> None:
        """Move selection up."""
        if self._active_panel == 0:
            selector = self.query_one("#ticket-selector", TicketSelector)
            selector.select_prev()
        else:
            # Navigate within tree sections
            self.notify("Tree navigation not fully implemented")

    def action_switch_panel(self) -> None:
        """Switch between selector and tree panels."""
        self._active_panel = (self._active_panel + 1) % 2
        self._update_panel_focus()

    def action_jump_to_item(self) -> None:
        """Jump to the selected dependency item."""
        if self._active_panel == 1:
            self.notify("Jump to item not yet implemented")
            # TODO: Find selected item in tree and navigate to it

    def action_add_dependency(self) -> None:
        """Add a new dependency."""
        if not self._selected_ticket:
            self.notify("Select a ticket first")
            return

        self.notify("Add dependency modal not yet implemented")
        # TODO: Show modal to select target ticket and relation type

    def action_remove_dependency(self) -> None:
        """Remove a dependency."""
        if not self._selected_ticket:
            self.notify("Select a ticket first")
            return

        self.notify("Remove dependency not yet implemented")
        # TODO: Show confirmation and remove selected dependency
