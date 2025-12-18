"""Modal screens for quick actions."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, TextArea, Select, Label
from textual.message import Message

from ...local_tickets import LocalTicket, TicketStatus
from ..state import get_status_icon, get_priority_label, PRIORITY_DISPLAY


class CreateLocalTicketModal(ModalScreen):
    """Modal for creating a new local ticket."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Save"),
    ]

    DEFAULT_CSS = """
    CreateLocalTicketModal {
        align: center middle;
    }

    CreateLocalTicketModal .modal-container {
        width: 70%;
        min-width: 50;
        max-width: 80;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    CreateLocalTicketModal .modal-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    CreateLocalTicketModal .modal-body {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    CreateLocalTicketModal .form-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    CreateLocalTicketModal .form-label {
        width: 100%;
        color: $text-muted;
        margin-bottom: 0;
    }

    CreateLocalTicketModal Input {
        width: 100%;
    }

    CreateLocalTicketModal TextArea {
        width: 100%;
        height: 5;
    }

    CreateLocalTicketModal Select {
        width: 100%;
    }

    CreateLocalTicketModal .modal-footer {
        width: 100%;
        height: 3;
        align: center middle;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
    }

    CreateLocalTicketModal .modal-footer Button {
        margin: 0 1;
    }
    """

    class TicketCreated(Message):
        """Message sent when a ticket is created."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    PRIORITY_OPTIONS = [
        ("Urgent (4)", 4),
        ("High (3)", 3),
        ("Medium (2)", 2),
        ("Low (1)", 1),
        ("None (0)", 0),
    ]

    def compose(self) -> ComposeResult:
        """Create the modal UI."""
        with Container(classes="modal-container"):
            yield Static("Create New Ticket", classes="modal-header")

            with Container(classes="modal-body"):
                # Title
                with Container(classes="form-row"):
                    yield Label("Title:", classes="form-label")
                    yield Input(placeholder="Enter ticket title...", id="title-input")

                # Description
                with Container(classes="form-row"):
                    yield Label("Description:", classes="form-label")
                    yield TextArea(id="description-input")

                # Priority
                with Container(classes="form-row"):
                    yield Label("Priority:", classes="form-label")
                    yield Select(
                        self.PRIORITY_OPTIONS,
                        value=2,
                        id="priority-select",
                    )

                # Tags
                with Container(classes="form-row"):
                    yield Label("Tags (comma-separated):", classes="form-label")
                    yield Input(placeholder="tag1, tag2, ...", id="tags-input")

            with Horizontal(classes="modal-footer"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Create", variant="primary", id="create-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "create-btn":
            self.action_submit()

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Create the ticket and close the modal."""
        title_input = self.query_one("#title-input", Input)
        title = title_input.value.strip()

        if not title:
            self.notify("Title is required", severity="error")
            return

        description_input = self.query_one("#description-input", TextArea)
        description = description_input.text.strip() or None

        priority_select = self.query_one("#priority-select", Select)
        priority = priority_select.value if priority_select.value != Select.BLANK else 2

        tags_input = self.query_one("#tags-input", Input)
        tags_text = tags_input.value.strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()] if tags_text else None

        # Create the ticket
        ticket = self.app.ticket_manager.create(
            title=title,
            description=description,
            priority=priority,
            tags=tags,
        )

        self.dismiss(ticket)


class StatusChangeModal(ModalScreen):
    """Modal for quickly changing ticket status."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_pending", "Pending", show=False),
        Binding("2", "select_in_progress", "In Progress", show=False),
        Binding("3", "select_completed", "Completed", show=False),
        Binding("4", "select_blocked", "Blocked", show=False),
        Binding("5", "select_canceled", "Canceled", show=False),
    ]

    DEFAULT_CSS = """
    StatusChangeModal {
        align: center middle;
    }

    StatusChangeModal .modal-container {
        width: 50%;
        min-width: 35;
        max-width: 50;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    StatusChangeModal .modal-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    StatusChangeModal .status-list {
        width: 100%;
        height: auto;
    }

    StatusChangeModal .status-option {
        width: 100%;
        height: 2;
        padding: 0 1;
    }

    StatusChangeModal .status-option:hover {
        background: $surface-lighten-1;
    }

    StatusChangeModal .status-option.current {
        background: $primary-background;
    }

    StatusChangeModal .key-hint {
        color: $warning;
        text-style: bold;
    }
    """

    class StatusSelected(Message):
        """Message sent when a status is selected."""

        def __init__(self, status: str):
            self.status = status
            super().__init__()

    STATUSES = [
        ("1", "pending", "Pending"),
        ("2", "in_progress", "In Progress"),
        ("3", "completed", "Completed"),
        ("4", "blocked", "Blocked"),
        ("5", "canceled", "Canceled"),
    ]

    def __init__(self, ticket: LocalTicket, **kwargs):
        """Initialize the modal.

        Args:
            ticket: The ticket to change status for
        """
        super().__init__(**kwargs)
        self.ticket = ticket

    def compose(self) -> ComposeResult:
        """Create the modal UI."""
        with Container(classes="modal-container"):
            yield Static(f"Change Status: {self.ticket.title[:25]}...", classes="modal-header")

            with Container(classes="status-list"):
                for key, status, label in self.STATUSES:
                    icon = get_status_icon(status)
                    is_current = status == self.ticket.status
                    option = Static(
                        f"[{key}] {icon} {label}",
                        classes="status-option" + (" current" if is_current else ""),
                        id=f"status-{status}",
                    )
                    option.status = status
                    yield option

    def _select_status(self, status: str) -> None:
        """Select a status and close."""
        if status != self.ticket.status:
            self.app.ticket_manager.update(self.ticket.id, status=status)
            self.dismiss(status)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel and close."""
        self.dismiss(None)

    def action_select_pending(self) -> None:
        self._select_status("pending")

    def action_select_in_progress(self) -> None:
        self._select_status("in_progress")

    def action_select_completed(self) -> None:
        self._select_status("completed")

    def action_select_blocked(self) -> None:
        self._select_status("blocked")

    def action_select_canceled(self) -> None:
        self._select_status("canceled")

    def on_click(self, event) -> None:
        """Handle click on status option."""
        target = event.widget
        if hasattr(target, "status"):
            self._select_status(target.status)


class EditLocalTicketModal(ModalScreen):
    """Modal for editing an existing local ticket."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Save"),
    ]

    DEFAULT_CSS = """
    EditLocalTicketModal {
        align: center middle;
    }

    EditLocalTicketModal .modal-container {
        width: 70%;
        min-width: 50;
        max-width: 80;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    EditLocalTicketModal .modal-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    EditLocalTicketModal .modal-body {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    EditLocalTicketModal .form-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    EditLocalTicketModal .form-label {
        width: 100%;
        color: $text-muted;
    }

    EditLocalTicketModal Input {
        width: 100%;
    }

    EditLocalTicketModal TextArea {
        width: 100%;
        height: 5;
    }

    EditLocalTicketModal Select {
        width: 100%;
    }

    EditLocalTicketModal .modal-footer {
        width: 100%;
        height: 3;
        align: center middle;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
    }

    EditLocalTicketModal .modal-footer Button {
        margin: 0 1;
    }
    """

    class TicketUpdated(Message):
        """Message sent when a ticket is updated."""

        def __init__(self, ticket: LocalTicket):
            self.ticket = ticket
            super().__init__()

    PRIORITY_OPTIONS = [
        ("Urgent (4)", 4),
        ("High (3)", 3),
        ("Medium (2)", 2),
        ("Low (1)", 1),
        ("None (0)", 0),
    ]

    def __init__(self, ticket: LocalTicket, **kwargs):
        """Initialize the modal.

        Args:
            ticket: The ticket to edit
        """
        super().__init__(**kwargs)
        self.ticket = ticket

    def compose(self) -> ComposeResult:
        """Create the modal UI."""
        with Container(classes="modal-container"):
            yield Static("Edit Ticket", classes="modal-header")

            with Container(classes="modal-body"):
                # Title
                with Container(classes="form-row"):
                    yield Label("Title:", classes="form-label")
                    yield Input(
                        value=self.ticket.title,
                        placeholder="Enter ticket title...",
                        id="title-input"
                    )

                # Description
                with Container(classes="form-row"):
                    yield Label("Description:", classes="form-label")
                    yield TextArea(id="description-input")

                # Priority
                with Container(classes="form-row"):
                    yield Label("Priority:", classes="form-label")
                    yield Select(
                        self.PRIORITY_OPTIONS,
                        value=self.ticket.priority,
                        id="priority-select",
                    )

                # Tags
                with Container(classes="form-row"):
                    yield Label("Tags (comma-separated):", classes="form-label")
                    yield Input(
                        value=", ".join(self.ticket.tags) if self.ticket.tags else "",
                        placeholder="tag1, tag2, ...",
                        id="tags-input"
                    )

            with Horizontal(classes="modal-footer"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Save", variant="primary", id="save-btn")

    def on_mount(self) -> None:
        """Set initial values after mount."""
        # Set description text
        description_input = self.query_one("#description-input", TextArea)
        if self.ticket.description:
            description_input.load_text(self.ticket.description)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "save-btn":
            self.action_submit()

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Save changes and close the modal."""
        title_input = self.query_one("#title-input", Input)
        title = title_input.value.strip()

        if not title:
            self.notify("Title is required", severity="error")
            return

        description_input = self.query_one("#description-input", TextArea)
        description = description_input.text.strip() or None

        priority_select = self.query_one("#priority-select", Select)
        priority = priority_select.value if priority_select.value != Select.BLANK else self.ticket.priority

        tags_input = self.query_one("#tags-input", Input)
        tags_text = tags_input.value.strip()
        tags = [t.strip() for t in tags_text.split(",") if t.strip()] if tags_text else []

        # Update the ticket
        updated_ticket = self.app.ticket_manager.update(
            self.ticket.id,
            title=title,
            description=description,
            priority=priority,
            tags=tags,
        )

        self.dismiss(updated_ticket)


class AddDependencyModal(ModalScreen):
    """Modal for adding a dependency between tickets."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    AddDependencyModal {
        align: center middle;
    }

    AddDependencyModal .modal-container {
        width: 70%;
        min-width: 50;
        max-width: 80;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    AddDependencyModal .modal-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
    }

    AddDependencyModal .modal-body {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    AddDependencyModal .form-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    AddDependencyModal .form-label {
        width: 100%;
        color: $text-muted;
    }

    AddDependencyModal .ticket-list {
        width: 100%;
        height: 15;
        overflow-y: auto;
        border: solid $surface-lighten-1;
    }

    AddDependencyModal .ticket-option {
        width: 100%;
        height: 2;
        padding: 0 1;
    }

    AddDependencyModal .ticket-option:hover {
        background: $surface-lighten-1;
    }

    AddDependencyModal .ticket-option.selected {
        background: $primary-background;
    }

    AddDependencyModal Select {
        width: 100%;
    }

    AddDependencyModal .modal-footer {
        width: 100%;
        height: 3;
        align: center middle;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
    }

    AddDependencyModal .modal-footer Button {
        margin: 0 1;
    }
    """

    RELATION_OPTIONS = [
        ("Blocks (source blocks target)", "blocks"),
        ("Related to", "related_to"),
    ]

    def __init__(self, source_ticket: LocalTicket, available_tickets: list[LocalTicket], **kwargs):
        """Initialize the modal.

        Args:
            source_ticket: The ticket to add a dependency from
            available_tickets: List of tickets to select as target
        """
        super().__init__(**kwargs)
        self.source_ticket = source_ticket
        # Filter out the source ticket
        self.available_tickets = [t for t in available_tickets if t.id != source_ticket.id]
        self.selected_target_index = 0

    def compose(self) -> ComposeResult:
        """Create the modal UI."""
        with Container(classes="modal-container"):
            source_title = self.source_ticket.title
            if len(source_title) > 30:
                source_title = source_title[:27] + "..."
            yield Static(f"Add Dependency from: {source_title}", classes="modal-header")

            with Container(classes="modal-body"):
                # Relation type
                with Container(classes="form-row"):
                    yield Label("Relation:", classes="form-label")
                    yield Select(
                        self.RELATION_OPTIONS,
                        value="blocks",
                        id="relation-select",
                    )

                # Target ticket selection
                with Container(classes="form-row"):
                    yield Label("Target Ticket:", classes="form-label")
                    with Container(classes="ticket-list", id="ticket-list"):
                        for i, ticket in enumerate(self.available_tickets):
                            yield self._create_ticket_option(ticket, i)

            with Horizontal(classes="modal-footer"):
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Add", variant="primary", id="add-btn")

    def _create_ticket_option(self, ticket: LocalTicket, index: int) -> Static:
        """Create a ticket option widget."""
        icon = get_status_icon(ticket.status)
        title = ticket.title
        if len(title) > 40:
            title = title[:37] + "..."

        widget = Static(f"{icon} {title}", classes="ticket-option", id=f"ticket-opt-{index}")
        widget.ticket = ticket
        widget.index = index

        if index == 0:
            widget.add_class("selected")

        return widget

    def on_click(self, event) -> None:
        """Handle click on ticket option."""
        target = event.widget
        if hasattr(target, "ticket") and hasattr(target, "index"):
            self._select_target(target.index)

    def _select_target(self, index: int) -> None:
        """Select a target ticket."""
        # Remove old selection
        for opt in self.query(".ticket-option"):
            opt.remove_class("selected")

        # Add new selection
        self.selected_target_index = index
        opt = self.query_one(f"#ticket-opt-{index}", Static)
        opt.add_class("selected")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "add-btn":
            self._add_dependency()

    def action_cancel(self) -> None:
        """Cancel and close."""
        self.dismiss(None)

    def _add_dependency(self) -> None:
        """Add the dependency and close."""
        if not self.available_tickets:
            self.notify("No tickets available", severity="error")
            return

        target_ticket = self.available_tickets[self.selected_target_index]

        relation_select = self.query_one("#relation-select", Select)
        relation = relation_select.value if relation_select.value != Select.BLANK else "blocks"

        # Add the dependency
        self.app.dep_manager.add(
            source_id=self.source_ticket.id,
            target_id=target_ticket.id,
            relation=relation,
            source_type="local",
            target_type="local",
        )

        self.dismiss({
            "source": self.source_ticket,
            "target": target_ticket,
            "relation": relation,
        })


class ConfirmDeleteModal(ModalScreen):
    """Modal for confirming ticket deletion."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
    ]

    DEFAULT_CSS = """
    ConfirmDeleteModal {
        align: center middle;
    }

    ConfirmDeleteModal .modal-container {
        width: 60%;
        min-width: 40;
        max-width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    ConfirmDeleteModal .modal-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        color: $error;
        padding-bottom: 1;
        border-bottom: solid $error;
        margin-bottom: 1;
    }

    ConfirmDeleteModal .modal-body {
        width: 100%;
        text-align: center;
        padding: 1;
    }

    ConfirmDeleteModal .ticket-title {
        text-style: bold;
        padding: 1 0;
    }

    ConfirmDeleteModal .modal-footer {
        width: 100%;
        height: 3;
        align: center middle;
        padding-top: 1;
    }

    ConfirmDeleteModal .modal-footer Button {
        margin: 0 1;
    }
    """

    def __init__(self, ticket: LocalTicket, **kwargs):
        """Initialize the modal.

        Args:
            ticket: The ticket to delete
        """
        super().__init__(**kwargs)
        self.ticket = ticket

    def compose(self) -> ComposeResult:
        """Create the modal UI."""
        with Container(classes="modal-container"):
            yield Static("Confirm Delete", classes="modal-header")

            with Container(classes="modal-body"):
                yield Static("Are you sure you want to delete this ticket?")
                yield Static(self.ticket.title, classes="ticket-title")
                yield Static("This action cannot be undone.")

            with Horizontal(classes="modal-footer"):
                yield Button("[N]o, Cancel", variant="default", id="cancel-btn")
                yield Button("[Y]es, Delete", variant="error", id="delete-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "delete-btn":
            self.action_confirm()

    def action_cancel(self) -> None:
        """Cancel and close."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Confirm deletion."""
        self.app.ticket_manager.delete(self.ticket.id)
        self.dismiss(True)
