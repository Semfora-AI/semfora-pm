"""Help screen showing all keybindings and shortcuts."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Static, Footer


class HelpScreen(ModalScreen):
    """Modal screen showing all available keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen .help-container {
        width: 70%;
        min-width: 60;
        max-width: 90;
        height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    HelpScreen .help-header {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
        margin-bottom: 1;
        color: $primary;
    }

    HelpScreen .help-content {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }

    HelpScreen .section-header {
        width: 100%;
        text-style: bold;
        color: $secondary;
        margin-top: 1;
        margin-bottom: 1;
    }

    HelpScreen .keybinding {
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    HelpScreen .key {
        color: $warning;
        text-style: bold;
    }

    HelpScreen .description {
        color: $text;
    }

    HelpScreen .help-footer {
        width: 100%;
        text-align: center;
        color: $text-muted;
        padding-top: 1;
        border-top: solid $surface-lighten-1;
        margin-top: 1;
    }
    """

    # All keybindings organized by section
    KEYBINDINGS = {
        "Global": [
            ("q", "Quit the application"),
            ("d", "Open Dashboard screen"),
            ("t", "Open Tickets screen"),
            ("g", "Open Dependency Graph screen"),
            ("n", "Create a new ticket"),
            ("?", "Show this help screen"),
            ("Ctrl+r", "Refresh all data"),
        ],
        "Dashboard Screen": [
            ("Tab", "Move to next column"),
            ("Shift+Tab", "Move to previous column"),
            ("j / ↓", "Move down in current column"),
            ("k / ↑", "Move up in current column"),
            ("Enter", "View selected ticket"),
            ("s", "Cycle status of selected ticket"),
            ("Escape", "Go back"),
        ],
        "Tickets Screen": [
            ("j / ↓", "Move down in list"),
            ("k / ↑", "Move up in list"),
            ("Enter", "View ticket details"),
            ("s", "Change status"),
            ("P (Shift+p)", "Cycle priority"),
            ("e", "Edit ticket"),
            ("d", "Delete ticket"),
            ("c", "Clear all filters"),
            ("/", "Focus filter bar"),
            ("Escape", "Go back"),
        ],
        "Dependencies Screen": [
            ("Tab", "Switch between panels"),
            ("j / ↓", "Move down"),
            ("k / ↑", "Move up"),
            ("Escape", "Go back"),
        ],
        "Modals & Forms": [
            ("Escape", "Cancel / Close"),
            ("Ctrl+s", "Save / Submit"),
            ("y", "Yes (in confirmation dialogs)"),
            ("n", "No (in confirmation dialogs)"),
        ],
    }

    def compose(self) -> ComposeResult:
        """Create the help screen UI."""
        with Container(classes="help-container"):
            yield Static("Semfora PM - Keyboard Shortcuts", classes="help-header")

            with ScrollableContainer(classes="help-content"):
                for section, bindings in self.KEYBINDINGS.items():
                    yield Static(f"━━━ {section} ━━━", classes="section-header")
                    for key, description in bindings:
                        yield Static(
                            f"  [{key}]  {description}",
                            classes="keybinding"
                        )

            yield Static(
                "Press [Escape], [q], or [?] to close this help",
                classes="help-footer"
            )

    def action_dismiss(self) -> None:
        """Close the help screen."""
        self.dismiss()
