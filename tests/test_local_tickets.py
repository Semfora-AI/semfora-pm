"""Tests for the local_tickets module."""

from pathlib import Path

import pytest

from semfora_pm.db import Database
from semfora_pm.local_tickets import LocalTicketManager, LocalTicket


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
def manager(db: Database, project_id: str) -> LocalTicketManager:
    """Create a LocalTicketManager for testing."""
    return LocalTicketManager(db, project_id)


class TestLocalTicketManager:
    """Tests for LocalTicketManager class."""

    def test_create_ticket(self, manager: LocalTicketManager):
        """Test creating a basic ticket."""
        ticket = manager.create(title="Test Ticket")

        assert ticket is not None
        assert ticket.title == "Test Ticket"
        assert ticket.status == "pending"
        assert ticket.priority == 2  # Default

    def test_create_ticket_with_all_fields(self, manager: LocalTicketManager):
        """Test creating a ticket with all optional fields."""
        ticket = manager.create(
            title="Full Ticket",
            description="A detailed description",
            priority=4,
            tags=["urgent", "backend"],
        )

        assert ticket.title == "Full Ticket"
        assert ticket.description == "A detailed description"
        assert ticket.priority == 4
        assert ticket.tags == ["urgent", "backend"]

    def test_get_ticket(self, manager: LocalTicketManager):
        """Test retrieving a ticket by ID."""
        created = manager.create(title="Get Test")
        fetched = manager.get(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "Get Test"

    def test_get_nonexistent_ticket(self, manager: LocalTicketManager):
        """Test getting a ticket that doesn't exist."""
        result = manager.get("nonexistent-id")
        assert result is None

    def test_update_ticket_title(self, manager: LocalTicketManager):
        """Test updating ticket title."""
        ticket = manager.create(title="Original")
        updated = manager.update(ticket.id, title="Updated")

        assert updated.title == "Updated"

    def test_update_ticket_status(self, manager: LocalTicketManager):
        """Test updating ticket status."""
        ticket = manager.create(title="Status Test")

        # Move to in_progress
        updated = manager.update(ticket.id, status="in_progress")
        assert updated.status == "in_progress"

        # Complete it
        updated = manager.update(ticket.id, status="completed")
        assert updated.status == "completed"
        assert updated.completed_at is not None

    def test_update_status_clears_completed_at(self, manager: LocalTicketManager):
        """Test that moving away from completed clears completed_at."""
        ticket = manager.create(title="Completed Test")
        manager.update(ticket.id, status="completed")

        # Move back to pending
        updated = manager.update(ticket.id, status="pending")
        assert updated.status == "pending"
        assert updated.completed_at is None

    def test_update_ticket_priority(self, manager: LocalTicketManager):
        """Test updating ticket priority."""
        ticket = manager.create(title="Priority Test", priority=2)
        updated = manager.update(ticket.id, priority=4)

        assert updated.priority == 4

    def test_update_ticket_tags(self, manager: LocalTicketManager):
        """Test updating ticket tags."""
        ticket = manager.create(title="Tags Test", tags=["old"])
        updated = manager.update(ticket.id, tags=["new", "tags"])

        assert updated.tags == ["new", "tags"]

    def test_list_tickets(self, manager: LocalTicketManager):
        """Test listing tickets."""
        manager.create(title="Ticket 1")
        manager.create(title="Ticket 2")
        manager.create(title="Ticket 3")

        tickets = manager.list()

        assert len(tickets) == 3

    def test_list_tickets_by_status(self, manager: LocalTicketManager):
        """Test filtering tickets by status."""
        ticket1 = manager.create(title="Pending")
        ticket2 = manager.create(title="In Progress")
        manager.update(ticket2.id, status="in_progress")

        pending = manager.list(status="pending")
        assert len(pending) == 1
        assert pending[0].title == "Pending"

        in_progress = manager.list(status="in_progress")
        assert len(in_progress) == 1
        assert in_progress[0].title == "In Progress"

    def test_list_excludes_completed_by_default(self, manager: LocalTicketManager):
        """Test that completed tickets are excluded by default."""
        ticket1 = manager.create(title="Active")
        ticket2 = manager.create(title="Completed")
        manager.update(ticket2.id, status="completed")

        tickets = manager.list()
        assert len(tickets) == 1
        assert tickets[0].title == "Active"

    def test_list_includes_completed_when_requested(self, manager: LocalTicketManager):
        """Test including completed tickets."""
        ticket1 = manager.create(title="Active")
        ticket2 = manager.create(title="Completed")
        manager.update(ticket2.id, status="completed")

        tickets = manager.list(include_completed=True)
        assert len(tickets) == 2

    def test_list_by_tags(self, manager: LocalTicketManager):
        """Test filtering tickets by tags."""
        manager.create(title="Backend", tags=["backend"])
        manager.create(title="Frontend", tags=["frontend"])
        manager.create(title="Both", tags=["backend", "frontend"])

        backend = manager.list(tags=["backend"])
        assert len(backend) == 2

        frontend = manager.list(tags=["frontend"])
        assert len(frontend) == 2

    def test_list_sorted_by_priority(self, manager: LocalTicketManager):
        """Test tickets are sorted by priority (highest first)."""
        manager.create(title="Low", priority=1)
        manager.create(title="High", priority=4)
        manager.create(title="Medium", priority=2)

        tickets = manager.list()

        assert tickets[0].priority == 4
        assert tickets[1].priority == 2
        assert tickets[2].priority == 1

    def test_delete_ticket(self, manager: LocalTicketManager):
        """Test deleting a ticket."""
        ticket = manager.create(title="To Delete")
        assert manager.get(ticket.id) is not None

        deleted = manager.delete(ticket.id)

        assert deleted is True
        assert manager.get(ticket.id) is None

    def test_delete_nonexistent_ticket(self, manager: LocalTicketManager):
        """Test deleting a ticket that doesn't exist."""
        deleted = manager.delete("nonexistent-id")
        assert deleted is False

    def test_mark_orphaned(self, db: Database, manager: LocalTicketManager):
        """Test marking tickets as orphaned when external item is removed."""
        # Create an external item first
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO external_items (id, project_id, provider_id, item_type, title)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ext-123", "test-project", "SEM-123", "ticket", "Test Ticket"),
            )

        # Create tickets linked to it
        ticket1 = manager.create(title="Linked 1", parent_ticket_id="ext-123")
        ticket2 = manager.create(title="Linked 2", parent_ticket_id="ext-123")
        ticket3 = manager.create(title="Unlinked")

        # Mark as orphaned
        count = manager.mark_orphaned("ext-123")

        assert count == 2

        # Verify status
        t1 = manager.get(ticket1.id)
        t2 = manager.get(ticket2.id)
        t3 = manager.get(ticket3.id)

        assert t1.status == "orphaned"
        assert t2.status == "orphaned"
        assert t3.status == "pending"  # Unchanged

    def test_reorder_tickets(self, manager: LocalTicketManager):
        """Test reordering tickets."""
        ticket1 = manager.create(title="First")
        ticket2 = manager.create(title="Second")
        ticket3 = manager.create(title="Third")

        # Reorder: Third, First, Second
        manager.reorder([ticket3.id, ticket1.id, ticket2.id])

        # Verify order
        t1 = manager.get(ticket1.id)
        t2 = manager.get(ticket2.id)
        t3 = manager.get(ticket3.id)

        assert t3.order_index == 0
        assert t1.order_index == 1
        assert t2.order_index == 2


class TestLocalTicketWithExternalItem:
    """Tests for tickets linked to external items."""

    def test_ticket_with_external_item(self, db: Database, manager: LocalTicketManager):
        """Test creating a ticket linked to an external item."""
        # Create external item
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO external_items (
                    id, project_id, provider_id, item_type, title,
                    epic_id, epic_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ext-456", "test-project", "SEM-456", "ticket",
                    "External Ticket", "epic-1", "Auth Epic",
                ),
            )

        # Create linked ticket
        ticket = manager.create(
            title="Implementation",
            parent_ticket_id="ext-456",
        )

        # Fetch with denormalized data
        fetched = manager.get(ticket.id)

        assert fetched.parent_ticket_id == "ext-456"
        assert fetched.linked_ticket_id == "SEM-456"
        assert fetched.linked_ticket_title == "External Ticket"
        assert fetched.linked_epic_id == "epic-1"
        assert fetched.linked_epic_name == "Auth Epic"
