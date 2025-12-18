"""Database connection management for semfora-pm local storage."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from .schema import SCHEMA_VERSION, get_migration_sql


class Database:
    """SQLite database wrapper with migration support.

    Usage:
        db = Database(Path(".pm/cache.db"))

        # Simple query
        with db.connection() as conn:
            rows = conn.execute("SELECT * FROM local_plans").fetchall()

        # Transaction with auto-commit/rollback
        with db.transaction() as conn:
            conn.execute("INSERT INTO local_plans ...")
            conn.execute("INSERT INTO dependencies ...")
    """

    def __init__(self, db_path: Path):
        """Initialize database, running migrations if needed.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._ensure_directory()
        self._migrate()

    def _ensure_directory(self) -> None:
        """Create parent directory if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with row factory.

        Yields:
            sqlite3.Connection configured with Row factory

        Example:
            with db.connection() as conn:
                row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
                if row:
                    print(row["title"])
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection with automatic commit/rollback.

        Commits on successful exit, rolls back on exception.

        Yields:
            sqlite3.Connection in a transaction

        Example:
            with db.transaction() as conn:
                conn.execute("INSERT INTO plans ...")
                conn.execute("INSERT INTO dependencies ...")
                # Automatically commits if no exception
        """
        with self.connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _migrate(self) -> None:
        """Run database migrations to bring schema up to date."""
        with self.transaction() as conn:
            # Create schema version table if it doesn't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Get current version
            result = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current_version = result[0] if result else 0

            if current_version < SCHEMA_VERSION:
                # Run migrations
                for sql in get_migration_sql(current_version, SCHEMA_VERSION):
                    conn.executescript(sql)

                # Record new version
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,)
                )

    def get_version(self) -> int:
        """Get current schema version.

        Returns:
            Current schema version number
        """
        with self.connection() as conn:
            result = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return result[0] if result else 0

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement (convenience method).

        For multiple statements or transactions, use connection() or transaction().

        Args:
            sql: SQL statement to execute
            params: Parameters for the statement

        Returns:
            Cursor from the execution
        """
        with self.connection() as conn:
            return conn.execute(sql, params)

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets.

        Args:
            sql: SQL statement to execute
            params_list: List of parameter tuples

        Returns:
            Cursor from the execution
        """
        with self.transaction() as conn:
            return conn.executemany(sql, params_list)
