"""Tests for the external_items module."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from semfora_pm.db import Database
from semfora_pm.external_items import (
    ExternalItemsManager,
    ExternalItem,
    normalize_linear_status,
    normalize_linear_priority,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    return Database(db_path)


@pytest.fixture
def project_id(db: Database) -> str:
    """Create a test project and return its ID."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
            ("test-project", "Test Project", "/test/path"),
        )
    return "test-project"


@pytest.fixture
def manager(db: Database, project_id: str) -> ExternalItemsManager:
    """Create an ExternalItemsManager for testing."""
    return ExternalItemsManager(db, project_id)


class TestExternalItemsManager:
    """Tests for ExternalItemsManager class."""

    def test_cache_item_new(self, manager: ExternalItemsManager):
        """Test caching a new external item."""
        item = manager.cache_item(
            provider_id="SEM-123",
            title="Test Ticket",
            item_type="ticket",
            status="In Progress",
            status_category="in_progress",
            priority=3,
        )

        assert item is not None
        assert item.provider_id == "SEM-123"
        assert item.title == "Test Ticket"
        assert item.status == "In Progress"
        assert item.status_category == "in_progress"
        assert item.priority == 3

    def test_cache_item_with_all_fields(self, manager: ExternalItemsManager):
        """Test caching an item with all optional fields."""
        item = manager.cache_item(
            provider_id="SEM-456",
            title="Full Ticket",
            item_type="ticket",
            description="A detailed description",
            status="Todo",
            status_category="todo",
            priority=2,
            assignee="user-123",
            assignee_name="John Doe",
            labels=["backend", "urgent"],
            epic_id="epic-1",
            epic_name="Auth Epic",
            sprint_id="sprint-1",
            sprint_name="Sprint 5",
            url="https://linear.app/team/SEM-456",
            provider_data={"key": "value"},
            created_at_provider="2024-01-01T00:00:00Z",
            updated_at_provider="2024-01-15T00:00:00Z",
        )

        assert item.description == "A detailed description"
        assert item.assignee == "user-123"
        assert item.assignee_name == "John Doe"
        assert item.labels == ["backend", "urgent"]
        assert item.epic_id == "epic-1"
        assert item.epic_name == "Auth Epic"
        assert item.sprint_id == "sprint-1"
        assert item.sprint_name == "Sprint 5"
        assert item.url == "https://linear.app/team/SEM-456"
        assert item.provider_data == {"key": "value"}

    def test_cache_item_update(self, manager: ExternalItemsManager):
        """Test updating an existing cached item."""
        # First cache
        manager.cache_item(
            provider_id="SEM-789",
            title="Original Title",
            status="Todo",
        )

        # Update with same provider_id
        updated = manager.cache_item(
            provider_id="SEM-789",
            title="Updated Title",
            status="In Progress",
        )

        assert updated.title == "Updated Title"
        assert updated.status == "In Progress"

        # Verify only one item exists
        with manager.db.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM external_items WHERE provider_id = ?",
                ("SEM-789",),
            ).fetchone()
            assert count["c"] == 1

    def test_get_by_id(self, manager: ExternalItemsManager):
        """Test retrieving item by internal UUID."""
        item = manager.cache_item(
            provider_id="SEM-100",
            title="Test",
        )

        fetched = manager.get_by_id(item.id)

        assert fetched is not None
        assert fetched.id == item.id
        assert fetched.provider_id == "SEM-100"

    def test_get_by_provider_id(self, manager: ExternalItemsManager):
        """Test retrieving item by provider ID."""
        manager.cache_item(
            provider_id="SEM-200",
            title="Provider ID Test",
        )

        fetched = manager.get_by_provider_id("SEM-200")

        assert fetched is not None
        assert fetched.provider_id == "SEM-200"
        assert fetched.title == "Provider ID Test"

    def test_get_uuid_for_provider_id(self, manager: ExternalItemsManager):
        """Test getting internal UUID for a provider ID."""
        item = manager.cache_item(
            provider_id="SEM-300",
            title="UUID Test",
        )

        uuid = manager.get_uuid_for_provider_id("SEM-300")

        assert uuid == item.id

    def test_get_uuid_for_nonexistent(self, manager: ExternalItemsManager):
        """Test getting UUID for non-existent provider ID."""
        uuid = manager.get_uuid_for_provider_id("NONEXISTENT")
        assert uuid is None

    def test_get_provider_id_for_uuid(self, manager: ExternalItemsManager):
        """Test getting provider ID for internal UUID."""
        item = manager.cache_item(
            provider_id="SEM-400",
            title="Reverse Lookup",
        )

        provider_id = manager.get_provider_id_for_uuid(item.id)

        assert provider_id == "SEM-400"

    def test_list_by_epic(self, manager: ExternalItemsManager):
        """Test listing items by epic."""
        manager.cache_item(
            provider_id="SEM-501",
            title="Epic Item 1",
            epic_id="epic-auth",
        )
        manager.cache_item(
            provider_id="SEM-502",
            title="Epic Item 2",
            epic_id="epic-auth",
        )
        manager.cache_item(
            provider_id="SEM-503",
            title="Different Epic",
            epic_id="epic-other",
        )

        items = manager.list_by_epic("epic-auth")

        assert len(items) == 2
        provider_ids = {i.provider_id for i in items}
        assert "SEM-501" in provider_ids
        assert "SEM-502" in provider_ids

    def test_is_stale_fresh_item(self, manager: ExternalItemsManager):
        """Test that recently cached item is not stale."""
        manager.cache_item(
            provider_id="SEM-600",
            title="Fresh",
        )

        is_stale = manager.is_stale("SEM-600", max_age_seconds=300)

        assert is_stale is False

    def test_is_stale_old_item(self, db: Database, manager: ExternalItemsManager):
        """Test that old cached item is stale."""
        # Manually insert with old timestamp
        old_time = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO external_items (
                    id, project_id, provider_id, item_type, title, cached_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("stale-id", "test-project", "SEM-700", "ticket", "Old", old_time),
            )

        is_stale = manager.is_stale("SEM-700", max_age_seconds=300)

        assert is_stale is True

    def test_is_stale_nonexistent(self, manager: ExternalItemsManager):
        """Test that non-existent item is considered stale."""
        is_stale = manager.is_stale("NONEXISTENT")
        assert is_stale is True

    def test_delete(self, manager: ExternalItemsManager):
        """Test deleting a cached item."""
        item = manager.cache_item(
            provider_id="SEM-800",
            title="To Delete",
        )

        deleted = manager.delete(item.id)

        assert deleted is True
        assert manager.get_by_id(item.id) is None

    def test_delete_nonexistent(self, manager: ExternalItemsManager):
        """Test deleting non-existent item."""
        deleted = manager.delete("nonexistent-id")
        assert deleted is False


class TestNormalizeLinearStatus:
    """Tests for normalize_linear_status function."""

    @pytest.mark.parametrize(
        "status,expected",
        [
            ("Backlog", "todo"),
            ("Triage", "todo"),
            ("Todo", "todo"),
            ("Unstarted", "todo"),
            ("In Progress", "in_progress"),
            ("in_progress", "in_progress"),
            ("Started", "in_progress"),
            ("Done", "done"),
            ("Completed", "done"),
            ("Merged", "done"),
            ("Canceled", "canceled"),
            ("Cancelled", "canceled"),
            ("Duplicate", "canceled"),
            ("Won't Fix", "canceled"),
            ("Unknown Status", "todo"),  # Default
        ],
    )
    def test_normalize_status(self, status: str, expected: str):
        """Test status normalization."""
        assert normalize_linear_status(status) == expected


class TestNormalizeLinearPriority:
    """Tests for normalize_linear_priority function."""

    @pytest.mark.parametrize(
        "priority,expected",
        [
            (None, 0),   # No priority
            (0, 0),      # None in Linear
            (1, 4),      # Urgent -> 4
            (2, 3),      # High -> 3
            (3, 2),      # Medium -> 2
            (4, 1),      # Low -> 1
        ],
    )
    def test_normalize_priority(self, priority, expected):
        """Test priority normalization (inverting Linear's scale)."""
        assert normalize_linear_priority(priority) == expected
