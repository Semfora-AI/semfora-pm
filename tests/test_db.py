"""Tests for the database module."""

import tempfile
from pathlib import Path

import pytest

from semfora_pm.db import Database, SCHEMA_VERSION


class TestDatabase:
    """Tests for Database class."""

    def test_database_creation(self, tmp_path: Path):
        """Test database is created with correct schema."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        assert db_path.exists()

        # Verify tables exist
        with db.connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [t["name"] for t in tables]

            assert "projects" in table_names
            assert "external_items" in table_names
            assert "local_tickets" in table_names
            assert "dependencies" in table_names
            assert "schema_version" in table_names

    def test_schema_version_tracking(self, tmp_path: Path):
        """Test schema version is recorded."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        with db.connection() as conn:
            row = conn.execute(
                "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            assert row["version"] == SCHEMA_VERSION

    def test_connection_context_manager(self, tmp_path: Path):
        """Test connection context manager."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        with db.connection() as conn:
            conn.execute("SELECT 1")
            # Connection should be open
            assert conn is not None

    def test_transaction_commit(self, tmp_path: Path):
        """Test transaction commits on success."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        # Insert a project
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
                ("test-id", "Test Project", "/test/path"),
            )

        # Verify it persisted
        with db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM projects WHERE id = ?", ("test-id",)
            ).fetchone()
            assert row["name"] == "Test Project"

    def test_transaction_rollback_on_error(self, tmp_path: Path):
        """Test transaction rolls back on exception."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        # First insert to have something in the database
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
                ("existing-id", "Existing", "/existing/path"),
            )

        # Try to insert with same ID (should fail)
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
                    ("existing-id", "Duplicate", "/duplicate/path"),
                )
        except Exception:
            pass  # Expected

        # Verify original data unchanged
        with db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM projects WHERE id = ?", ("existing-id",)
            ).fetchone()
            assert row["name"] == "Existing"

    def test_directory_creation(self, tmp_path: Path):
        """Test database directory is created if it doesn't exist."""
        nested_path = tmp_path / "nested" / "dir" / "test.db"
        db = Database(nested_path)

        assert nested_path.parent.exists()
        assert nested_path.exists()

    def test_row_factory_dict_access(self, tmp_path: Path):
        """Test rows can be accessed as dictionaries."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, config_path, provider) VALUES (?, ?, ?, ?)",
                ("dict-test", "Dict Test", "/dict/path", "linear"),
            )

        with db.connection() as conn:
            row = conn.execute(
                "SELECT id, name, provider FROM projects WHERE id = ?",
                ("dict-test",),
            ).fetchone()

            # Should be accessible by column name
            assert row["id"] == "dict-test"
            assert row["name"] == "Dict Test"
            assert row["provider"] == "linear"
