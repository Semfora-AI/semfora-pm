"""Database module for semfora-pm local storage.

This module provides SQLite-based persistence for local plans, dependencies,
and cached external items from providers like Linear.

Usage:
    from semfora_pm.db import Database

    db = Database(Path(".pm/cache.db"))

    with db.transaction() as conn:
        conn.execute("INSERT INTO local_plans ...")
"""

from .connection import Database
from .schema import SCHEMA_VERSION

__all__ = ["Database", "SCHEMA_VERSION"]
