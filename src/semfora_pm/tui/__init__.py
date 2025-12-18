"""Semfora PM Terminal User Interface.

This module provides an interactive TUI for managing local plans,
dependencies, and viewing connected provider tickets.
"""

from pathlib import Path


def run_tui(path: Path | None = None) -> None:
    """Launch the TUI application.

    Args:
        path: Optional directory path for PM context resolution.
              If not provided, uses current working directory.
    """
    from .app import SemforaPMApp

    app = SemforaPMApp(path)
    app.run()


__all__ = ["run_tui"]
