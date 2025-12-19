"""Tests for the unified TicketManager."""

import pytest
import uuid

from semfora_pm.db import Database
from semfora_pm.tickets import (
    TicketManager,
    Ticket,
    TicketSummary,
    AcceptanceCriterion,
)


@pytest.fixture
def db(tmp_path):
    """Create a test database."""
    db_path = tmp_path / ".pm" / "cache.db"
    database = Database(db_path)
    return database


@pytest.fixture
def project_id():
    """Create a test project ID."""
    return str(uuid.uuid4())


@pytest.fixture
def ticket_manager(db, project_id):
    """Create a TicketManager for testing."""
    # Create a project record first
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
            (project_id, "Test Project", "/tmp/test"),
        )
    return TicketManager(db, project_id)


class TestAcceptanceCriterion:
    """Tests for AcceptanceCriterion dataclass."""

    def test_to_dict(self):
        ac = AcceptanceCriterion(index=0, text="Test AC", status="pending")
        d = ac.to_dict()
        assert d["index"] == 0
        assert d["text"] == "Test AC"
        assert d["status"] == "pending"

    def test_to_dict_with_evidence(self):
        ac = AcceptanceCriterion(
            index=0, text="Test AC", status="verified", evidence="Test passed"
        )
        d = ac.to_dict()
        assert d["evidence"] == "Test passed"

    def test_from_dict(self):
        d = {"index": 1, "text": "AC Text", "status": "in_progress"}
        ac = AcceptanceCriterion.from_dict(d)
        assert ac.index == 1
        assert ac.text == "AC Text"
        assert ac.status == "in_progress"


class TestTicketManagerCreate:
    """Tests for creating tickets."""

    def test_create_basic_ticket(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test ticket")
        assert ticket_id is not None
        assert len(ticket_id) == 36  # UUID format

    def test_create_ticket_with_description(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test ticket",
            description="This is a test description",
        )

        ticket = ticket_manager.get(ticket_id)
        assert ticket.description == "This is a test description"

    def test_create_ticket_with_acceptance_criteria(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test ticket",
            acceptance_criteria=["AC 1", "AC 2", "AC 3"],
        )

        ticket = ticket_manager.get(ticket_id)
        assert len(ticket.acceptance_criteria) == 3
        assert ticket.acceptance_criteria[0].text == "AC 1"
        assert ticket.acceptance_criteria[0].status == "pending"

    def test_create_ticket_with_priority(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Urgent ticket", priority=4)
        ticket = ticket_manager.get(ticket_id)
        assert ticket.priority == 4

    def test_create_ticket_with_labels(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test ticket",
            labels=["bug", "urgent"],
        )
        ticket = ticket_manager.get(ticket_id)
        assert ticket.labels == ["bug", "urgent"]

    def test_create_ticket_with_tags(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test ticket",
            tags=["local", "implementation"],
        )
        ticket = ticket_manager.get(ticket_id)
        assert ticket.tags == ["local", "implementation"]

    def test_created_ticket_has_pending_status(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket = ticket_manager.get(ticket_id)
        assert ticket.status == "pending"
        assert ticket.status_category == "todo"


class TestTicketManagerGet:
    """Tests for getting tickets."""

    def test_get_existing_ticket(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test ticket")
        ticket = ticket_manager.get(ticket_id)
        assert ticket is not None
        assert ticket.title == "Test ticket"

    def test_get_nonexistent_ticket(self, ticket_manager):
        ticket = ticket_manager.get("nonexistent-id")
        assert ticket is None


class TestTicketManagerList:
    """Tests for listing tickets."""

    def test_list_all_tickets(self, ticket_manager):
        ticket_manager.create(title="Ticket 1")
        ticket_manager.create(title="Ticket 2")
        ticket_manager.create(title="Ticket 3")

        tickets = ticket_manager.list()
        assert len(tickets) == 3

    def test_list_by_source(self, ticket_manager):
        ticket_manager.create(title="Local ticket 1", source="local")
        ticket_manager.create(title="Local ticket 2", source="local")

        tickets = ticket_manager.list(source="local")
        assert len(tickets) == 2

    def test_list_by_status(self, ticket_manager):
        id1 = ticket_manager.create(title="Ticket 1")
        ticket_manager.create(title="Ticket 2")
        ticket_manager.update(id1, status="in_progress")

        tickets = ticket_manager.list(status="in_progress")
        assert len(tickets) == 1
        assert tickets[0].title == "Ticket 1"

    def test_list_by_status_category(self, ticket_manager):
        id1 = ticket_manager.create(title="Ticket 1")
        ticket_manager.create(title="Ticket 2")
        ticket_manager.update(id1, status_category="done")

        tickets = ticket_manager.list(status_category="done")
        assert len(tickets) == 1

    def test_list_by_priority(self, ticket_manager):
        ticket_manager.create(title="Low priority", priority=1)
        ticket_manager.create(title="High priority", priority=4)

        tickets = ticket_manager.list(priority=4)
        assert len(tickets) == 1
        assert tickets[0].title == "High priority"

    def test_list_with_limit(self, ticket_manager):
        for i in range(10):
            ticket_manager.create(title=f"Ticket {i}")

        tickets = ticket_manager.list(limit=5)
        assert len(tickets) == 5

    def test_list_with_offset(self, ticket_manager):
        for i in range(10):
            ticket_manager.create(title=f"Ticket {i}", priority=i % 5)

        tickets1 = ticket_manager.list(limit=5, offset=0)
        tickets2 = ticket_manager.list(limit=5, offset=5)

        # Should be different tickets
        ids1 = {t.id for t in tickets1}
        ids2 = {t.id for t in tickets2}
        assert ids1.isdisjoint(ids2)

    def test_list_returns_ticket_summary(self, ticket_manager):
        ticket_manager.create(
            title="Test",
            acceptance_criteria=["AC 1"],
        )

        tickets = ticket_manager.list()
        assert len(tickets) == 1
        assert isinstance(tickets[0], TicketSummary)
        assert tickets[0].has_ac is True


class TestTicketManagerUpdate:
    """Tests for updating tickets."""

    def test_update_title(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Original title")
        ticket_manager.update(ticket_id, title="New title")

        ticket = ticket_manager.get(ticket_id)
        assert ticket.title == "New title"

    def test_update_description(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket_manager.update(ticket_id, description="New description")

        ticket = ticket_manager.get(ticket_id)
        assert ticket.description == "New description"

    def test_update_status(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket_manager.update(ticket_id, status="in_progress")

        ticket = ticket_manager.get(ticket_id)
        assert ticket.status == "in_progress"

    def test_update_priority(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket_manager.update(ticket_id, priority=4)

        ticket = ticket_manager.get(ticket_id)
        assert ticket.priority == 4

    def test_update_labels(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket_manager.update(ticket_id, labels=["bug", "urgent"])

        ticket = ticket_manager.get(ticket_id)
        assert ticket.labels == ["bug", "urgent"]

    def test_update_returns_updated_ticket(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket = ticket_manager.update(ticket_id, title="Updated")

        assert ticket is not None
        assert ticket.title == "Updated"

    def test_update_nonexistent_returns_none(self, ticket_manager):
        ticket = ticket_manager.update("nonexistent-id", title="New")
        assert ticket is None

    def test_update_no_changes_returns_ticket(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        ticket = ticket_manager.update(ticket_id)
        assert ticket is not None
        assert ticket.title == "Test"


class TestTicketManagerAcceptanceCriteria:
    """Tests for acceptance criteria management."""

    def test_update_ac_status(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test",
            acceptance_criteria=["AC 1", "AC 2"],
        )

        result = ticket_manager.update_ac_status(ticket_id, 0, "verified", "Test passed")
        assert result is True

        ticket = ticket_manager.get(ticket_id)
        assert ticket.acceptance_criteria[0].status == "verified"
        assert ticket.acceptance_criteria[0].evidence == "Test passed"

    def test_update_ac_status_invalid_index(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test",
            acceptance_criteria=["AC 1"],
        )

        result = ticket_manager.update_ac_status(ticket_id, 99, "verified")
        assert result is False

    def test_add_acceptance_criterion(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        index = ticket_manager.add_acceptance_criterion(ticket_id, "New AC")

        assert index == 0

        ticket = ticket_manager.get(ticket_id)
        assert len(ticket.acceptance_criteria) == 1
        assert ticket.acceptance_criteria[0].text == "New AC"

    def test_add_acceptance_criterion_to_existing(self, ticket_manager):
        ticket_id = ticket_manager.create(
            title="Test",
            acceptance_criteria=["AC 1", "AC 2"],
        )

        index = ticket_manager.add_acceptance_criterion(ticket_id, "AC 3")
        assert index == 2

        ticket = ticket_manager.get(ticket_id)
        assert len(ticket.acceptance_criteria) == 3


class TestTicketManagerDelete:
    """Tests for deleting tickets."""

    def test_delete_ticket(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Test")
        result = ticket_manager.delete(ticket_id)

        assert result is True
        assert ticket_manager.get(ticket_id) is None

    def test_delete_nonexistent_ticket(self, ticket_manager):
        result = ticket_manager.delete("nonexistent-id")
        assert result is False


class TestTicketManagerSearch:
    """Tests for searching tickets."""

    def test_search_by_title(self, ticket_manager):
        ticket_manager.create(title="Implement JWT authentication")
        ticket_manager.create(title="Add user login")
        ticket_manager.create(title="Fix JWT bug")

        results = ticket_manager.search("JWT")
        assert len(results) == 2

    def test_search_by_description(self, ticket_manager):
        ticket_manager.create(
            title="Test ticket",
            description="This involves JWT tokens",
        )
        ticket_manager.create(title="Another ticket")

        results = ticket_manager.search("JWT")
        assert len(results) == 1

    def test_search_empty_query(self, ticket_manager):
        ticket_manager.create(title="Test")
        results = ticket_manager.search("")
        assert len(results) == 0

    def test_search_no_results(self, ticket_manager):
        ticket_manager.create(title="Test ticket")
        results = ticket_manager.search("nonexistent")
        assert len(results) == 0

    def test_search_with_limit(self, ticket_manager):
        for i in range(20):
            ticket_manager.create(title=f"Test ticket {i}")

        results = ticket_manager.search("Test", limit=5)
        assert len(results) == 5


class TestTicketManagerExternalLinking:
    """Tests for linking to external items."""

    def test_link_external(self, ticket_manager, db, project_id):
        # Create an external item first
        external_id = str(uuid.uuid4())
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO external_items (id, project_id, provider_id, item_type, title, url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (external_id, project_id, "SEM-123", "issue", "External ticket", "https://linear.app/sem/SEM-123"),
            )

        ticket_id = ticket_manager.create(title="Local ticket")
        result = ticket_manager.link_external(ticket_id, external_id)

        assert result is True

        ticket = ticket_manager.get(ticket_id)
        assert ticket.source == "linear"
        assert ticket.external_item_id == external_id

    def test_link_external_nonexistent_item(self, ticket_manager):
        ticket_id = ticket_manager.create(title="Local ticket")
        result = ticket_manager.link_external(ticket_id, "nonexistent-id")
        assert result is False

    def test_get_by_external_id(self, ticket_manager, db, project_id):
        # Create an external item
        external_id = str(uuid.uuid4())
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO external_items (id, project_id, provider_id, item_type, title, url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (external_id, project_id, "SEM-456", "issue", "External ticket", "https://linear.app/sem/SEM-456"),
            )

        # Create and link ticket
        ticket_id = ticket_manager.create(title="Linked ticket")
        ticket_manager.link_external(ticket_id, external_id)

        # Get by external ID
        ticket = ticket_manager.get_by_external_id("SEM-456")
        assert ticket is not None
        assert ticket.id == ticket_id
        assert ticket.external_id == "SEM-456"

    def test_get_by_external_id_not_found(self, ticket_manager):
        ticket = ticket_manager.get_by_external_id("NONEXISTENT-123")
        assert ticket is None
