"""Tests for the dependencies module."""

from pathlib import Path

import pytest

from semfora_pm.db import Database
from semfora_pm.local_tickets import LocalTicketManager
from semfora_pm.dependencies import DependencyManager


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
def ticket_manager(db: Database, project_id: str) -> LocalTicketManager:
    """Create a LocalTicketManager for testing."""
    return LocalTicketManager(db, project_id)


@pytest.fixture
def dep_manager(db: Database, project_id: str) -> DependencyManager:
    """Create a DependencyManager for testing."""
    return DependencyManager(db, project_id)


class TestDependencyManager:
    """Tests for DependencyManager class."""

    def test_add_dependency(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test adding a dependency between tickets."""
        ticket_a = ticket_manager.create(title="Ticket A")
        ticket_b = ticket_manager.create(title="Ticket B")

        dep = dep_manager.add(
            source_id=ticket_a.id,
            target_id=ticket_b.id,
            relation="blocks",
        )

        assert dep is not None
        assert dep.source_id == ticket_a.id
        assert dep.target_id == ticket_b.id
        assert dep.relation == "blocks"

    def test_add_dependency_with_notes(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test adding a dependency with notes."""
        ticket_a = ticket_manager.create(title="Ticket A")
        ticket_b = ticket_manager.create(title="Ticket B")

        dep = dep_manager.add(
            source_id=ticket_a.id,
            target_id=ticket_b.id,
            relation="blocks",
            notes="Must complete auth before API",
        )

        assert dep.notes == "Must complete auth before API"

    def test_remove_dependency(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test removing a dependency."""
        ticket_a = ticket_manager.create(title="Ticket A")
        ticket_b = ticket_manager.create(title="Ticket B")

        dep_manager.add(
            source_id=ticket_a.id,
            target_id=ticket_b.id,
            relation="blocks",
        )

        count = dep_manager.remove(
            source_id=ticket_a.id,
            target_id=ticket_b.id,
        )

        assert count == 1

    def test_get_blockers_direct(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test getting direct blockers."""
        ticket_a = ticket_manager.create(title="Blocker A")
        ticket_b = ticket_manager.create(title="Blocker B")
        ticket_target = ticket_manager.create(title="Target")

        # A and B both block Target
        dep_manager.add(ticket_a.id, ticket_target.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_target.id, "blocks")

        blockers = dep_manager.get_blockers(ticket_target.id)

        assert len(blockers) == 2
        blocker_ids = {b.item_id for b in blockers}
        assert ticket_a.id in blocker_ids
        assert ticket_b.id in blocker_ids

    def test_get_blockers_resolved(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test that resolved blockers are excluded by default."""
        ticket_a = ticket_manager.create(title="Blocker A")
        ticket_b = ticket_manager.create(title="Blocker B")
        ticket_target = ticket_manager.create(title="Target")

        dep_manager.add(ticket_a.id, ticket_target.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_target.id, "blocks")

        # Complete ticket_a
        ticket_manager.update(ticket_a.id, status="completed")

        blockers = dep_manager.get_blockers(ticket_target.id)

        assert len(blockers) == 1
        assert blockers[0].item_id == ticket_b.id

    def test_get_blockers_include_resolved(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test including resolved blockers."""
        ticket_a = ticket_manager.create(title="Blocker A")
        ticket_target = ticket_manager.create(title="Target")

        dep_manager.add(ticket_a.id, ticket_target.id, "blocks")
        ticket_manager.update(ticket_a.id, status="completed")

        blockers = dep_manager.get_blockers(ticket_target.id, include_resolved=True)

        assert len(blockers) == 1
        assert blockers[0].resolved is True

    def test_get_blockers_recursive(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test recursive blocker detection."""
        # Chain: A -> B -> C (A blocks B, B blocks C)
        ticket_a = ticket_manager.create(title="Ticket A")
        ticket_b = ticket_manager.create(title="Ticket B")
        ticket_c = ticket_manager.create(title="Ticket C")

        dep_manager.add(ticket_a.id, ticket_b.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_c.id, "blocks")

        # Non-recursive should only find B
        blockers = dep_manager.get_blockers(ticket_c.id, recursive=False)
        assert len(blockers) == 1
        assert blockers[0].item_id == ticket_b.id

        # Recursive should find both A and B
        blockers = dep_manager.get_blockers(ticket_c.id, recursive=True)
        assert len(blockers) == 2

        # Verify depths
        depths = {b.item_id: b.depth for b in blockers}
        assert depths[ticket_b.id] == 1
        assert depths[ticket_a.id] == 2

    def test_get_dependents(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test getting items blocked by this one."""
        ticket_blocker = ticket_manager.create(title="Blocker")
        ticket_a = ticket_manager.create(title="Dependent A")
        ticket_b = ticket_manager.create(title="Dependent B")

        dep_manager.add(ticket_blocker.id, ticket_a.id, "blocks")
        dep_manager.add(ticket_blocker.id, ticket_b.id, "blocks")

        dependents = dep_manager.get_dependents(ticket_blocker.id)

        assert len(dependents) == 2
        dependent_ids = {d.item_id for d in dependents}
        assert ticket_a.id in dependent_ids
        assert ticket_b.id in dependent_ids

    def test_get_ready_work_no_blockers(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test getting ready work with no blockers."""
        ticket_manager.create(title="Ready 1", priority=4)
        ticket_manager.create(title="Ready 2", priority=2)

        ready = dep_manager.get_ready_work()

        assert len(ready) == 2
        # Should be sorted by priority (highest first)
        assert ready[0].priority == 4
        assert ready[1].priority == 2

    def test_get_ready_work_with_blockers(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test that blocked items are excluded from ready work."""
        ticket_blocker = ticket_manager.create(title="Blocker")
        ticket_blocked = ticket_manager.create(title="Blocked")
        ticket_ready = ticket_manager.create(title="Ready")

        dep_manager.add(ticket_blocker.id, ticket_blocked.id, "blocks")

        ready = dep_manager.get_ready_work()

        ready_ids = {r.item_id for r in ready}
        assert ticket_blocker.id in ready_ids
        assert ticket_ready.id in ready_ids
        assert ticket_blocked.id not in ready_ids  # Blocked, so not ready

    def test_get_ready_work_blocker_resolved(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test that items become ready when blockers are resolved."""
        ticket_blocker = ticket_manager.create(title="Blocker")
        ticket_blocked = ticket_manager.create(title="Was Blocked")

        dep_manager.add(ticket_blocker.id, ticket_blocked.id, "blocks")

        # Initially blocked
        ready = dep_manager.get_ready_work()
        ready_ids = {r.item_id for r in ready}
        assert ticket_blocked.id not in ready_ids

        # Complete the blocker
        ticket_manager.update(ticket_blocker.id, status="completed")

        # Now should be ready
        ready = dep_manager.get_ready_work()
        ready_ids = {r.item_id for r in ready}
        assert ticket_blocked.id in ready_ids

    def test_get_ready_work_limit(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test limiting ready work results."""
        for i in range(10):
            ticket_manager.create(title=f"Ticket {i}")

        ready = dep_manager.get_ready_work(limit=3)
        assert len(ready) == 3

    def test_list_all_dependencies(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test listing all dependencies."""
        ticket_a = ticket_manager.create(title="A")
        ticket_b = ticket_manager.create(title="B")
        ticket_c = ticket_manager.create(title="C")

        dep_manager.add(ticket_a.id, ticket_b.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_c.id, "blocks")
        dep_manager.add(ticket_a.id, ticket_c.id, "related_to")

        deps = dep_manager.list_all()
        assert len(deps) == 3

    def test_list_dependencies_by_item(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test filtering dependencies by item."""
        ticket_a = ticket_manager.create(title="A")
        ticket_b = ticket_manager.create(title="B")
        ticket_c = ticket_manager.create(title="C")

        dep_manager.add(ticket_a.id, ticket_b.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_c.id, "blocks")

        # Get deps involving ticket_b
        deps = dep_manager.list_all(item_id=ticket_b.id)
        assert len(deps) == 2  # As source and target

    def test_list_dependencies_by_relation(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test filtering dependencies by relation type."""
        ticket_a = ticket_manager.create(title="A")
        ticket_b = ticket_manager.create(title="B")

        dep_manager.add(ticket_a.id, ticket_b.id, "blocks")
        dep_manager.add(ticket_a.id, ticket_b.id, "related_to")

        blocks = dep_manager.list_all(relation="blocks")
        assert len(blocks) == 1

        related = dep_manager.list_all(relation="related_to")
        assert len(related) == 1


class TestCycleDetection:
    """Tests for cycle handling in dependencies."""

    def test_no_infinite_loop_on_cycle(self, dep_manager: DependencyManager, ticket_manager: LocalTicketManager):
        """Test that recursive blocker detection handles cycles gracefully."""
        ticket_a = ticket_manager.create(title="A")
        ticket_b = ticket_manager.create(title="B")
        ticket_c = ticket_manager.create(title="C")

        # Create a cycle: A -> B -> C -> A
        dep_manager.add(ticket_a.id, ticket_b.id, "blocks")
        dep_manager.add(ticket_b.id, ticket_c.id, "blocks")
        dep_manager.add(ticket_c.id, ticket_a.id, "blocks")

        # Should complete without infinite loop
        blockers = dep_manager.get_blockers(ticket_a.id, recursive=True)

        # Should have found blockers without hanging
        assert len(blockers) >= 1
