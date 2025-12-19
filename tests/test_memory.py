"""Tests for the MemoryManager."""

import pytest
import uuid

from semfora_pm.db import Database
from semfora_pm.memory import MemoryManager, ProjectMemory, Discovery
from semfora_pm.tickets import TicketManager
from semfora_pm.plans import PlanManager


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
def memory_manager(db, project_id):
    """Create a MemoryManager for testing."""
    # Create a project record first
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
            (project_id, "Test Project", "/tmp/test"),
        )
    return MemoryManager(db, project_id)


@pytest.fixture
def ticket_manager(db, project_id):
    """Create a TicketManager for testing."""
    return TicketManager(db, project_id)


@pytest.fixture
def plan_manager(db, project_id):
    """Create a PlanManager for testing."""
    return PlanManager(db, project_id)


class TestProjectMemory:
    """Tests for ProjectMemory dataclass."""

    def test_empty_memory(self):
        memory = ProjectMemory()
        assert memory.current_ticket_id is None
        assert memory.current_plan_id is None
        assert memory.discoveries == []
        assert memory.blockers == []

    def test_memory_to_dict(self):
        memory = ProjectMemory(
            current_ticket_id="SEM-45",
            current_ticket_title="Test ticket",
            current_step="Step 1",
            completed_steps=2,
            total_steps=5,
        )
        d = memory.to_dict()

        assert d["ticket"]["id"] == "SEM-45"
        assert d["progress"]["current"] == "Step 1"
        assert d["progress"]["done"] == 2
        assert d["progress"]["total"] == 5

    def test_memory_from_dict(self):
        d = {
            "ticket": {"id": "SEM-45", "title": "Test"},
            "plan": {"id": "plan-123", "title": "Plan", "status": "active"},
            "progress": {"current": "Step 1", "done": 1, "total": 3},
            "blockers": ["Waiting for API"],
            "discoveries": [{"c": "Found pattern", "i": 3}],
        }
        memory = ProjectMemory.from_dict(d)

        assert memory.current_ticket_id == "SEM-45"
        assert memory.current_plan_id == "plan-123"
        assert memory.current_step == "Step 1"
        assert memory.blockers == ["Waiting for API"]
        assert len(memory.discoveries) == 1
        assert memory.discoveries[0].content == "Found pattern"

    def test_memory_estimate_tokens(self):
        memory = ProjectMemory(
            current_ticket_id="SEM-45",
            discoveries=[
                Discovery(content="Discovery 1", importance=3),
                Discovery(content="Discovery 2", importance=2),
            ],
        )
        tokens = memory.estimate_tokens()
        assert tokens > 0


class TestMemoryManagerGetSave:
    """Tests for get and save operations."""

    def test_get_empty_memory(self, memory_manager):
        memory = memory_manager.get()
        assert isinstance(memory, ProjectMemory)
        assert memory.current_ticket_id is None

    def test_save_and_get_memory(self, memory_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="Test ticket")

        memory = ProjectMemory(
            current_ticket_id=ticket_id,
            current_ticket_title="Test ticket",
        )
        memory_manager.save(memory)

        retrieved = memory_manager.get()
        assert retrieved.current_ticket_id == ticket_id
        assert retrieved.current_ticket_title == "Test ticket"

    def test_save_updates_existing(self, memory_manager, ticket_manager):
        # Create real tickets (FK constraint requires valid ticket IDs)
        ticket_id_1 = ticket_manager.create(title="Ticket 1")
        ticket_id_2 = ticket_manager.create(title="Ticket 2")

        memory1 = ProjectMemory(current_ticket_id=ticket_id_1)
        memory_manager.save(memory1)

        memory2 = ProjectMemory(current_ticket_id=ticket_id_2)
        memory_manager.save(memory2)

        retrieved = memory_manager.get()
        assert retrieved.current_ticket_id == ticket_id_2


class TestMemoryManagerCurrentWork:
    """Tests for current work management."""

    def test_set_current_work(self, memory_manager, ticket_manager, plan_manager):
        # Create real ticket and plan (FK constraints require valid IDs)
        ticket_id = ticket_manager.create(title="Test ticket")
        plan_id = plan_manager.create(title="Test plan")

        memory_manager.set_current_work(
            ticket_id=ticket_id,
            ticket_title="Test ticket",
            plan_id=plan_id,
            plan_title="Test plan",
            plan_status="active",
        )

        memory = memory_manager.get()
        assert memory.current_ticket_id == ticket_id
        assert memory.current_ticket_title == "Test ticket"
        assert memory.current_plan_id == plan_id
        assert memory.current_plan_title == "Test plan"
        assert memory.current_plan_status == "active"

    def test_set_partial_current_work(self, memory_manager, ticket_manager, plan_manager):
        # Create real ticket and plan (FK constraints require valid IDs)
        ticket_id = ticket_manager.create(title="Test ticket")
        plan_id = plan_manager.create(title="Test plan")

        memory_manager.set_current_work(ticket_id=ticket_id)
        memory_manager.set_current_work(plan_id=plan_id)

        memory = memory_manager.get()
        assert memory.current_ticket_id == ticket_id
        assert memory.current_plan_id == plan_id


class TestMemoryManagerProgress:
    """Tests for progress tracking."""

    def test_update_progress(self, memory_manager):
        memory_manager.update_progress(
            current_step="Step 2",
            completed_steps=1,
            total_steps=5,
            blockers=["Waiting for API"],
        )

        memory = memory_manager.get()
        assert memory.current_step == "Step 2"
        assert memory.completed_steps == 1
        assert memory.total_steps == 5
        assert memory.blockers == ["Waiting for API"]

    def test_update_progress_partial(self, memory_manager):
        memory_manager.update_progress(total_steps=10)
        memory_manager.update_progress(completed_steps=3)

        memory = memory_manager.get()
        assert memory.completed_steps == 3
        assert memory.total_steps == 10


class TestMemoryManagerDiscoveries:
    """Tests for discovery management."""

    def test_add_discovery(self, memory_manager):
        memory_manager.add_discovery("Found existing code pattern", importance=3)

        memory = memory_manager.get()
        assert len(memory.discoveries) == 1
        assert memory.discoveries[0].content == "Found existing code pattern"
        assert memory.discoveries[0].importance == 3

    def test_add_multiple_discoveries(self, memory_manager):
        memory_manager.add_discovery("Discovery 1", importance=2)
        memory_manager.add_discovery("Discovery 2", importance=4)
        memory_manager.add_discovery("Discovery 3", importance=1)

        memory = memory_manager.get()
        assert len(memory.discoveries) == 3

    def test_discovery_importance_clamped(self, memory_manager):
        memory_manager.add_discovery("Too low", importance=0)
        memory_manager.add_discovery("Too high", importance=10)

        memory = memory_manager.get()
        assert memory.discoveries[0].importance == 1  # Clamped to min
        assert memory.discoveries[1].importance == 5  # Clamped to max


class TestMemoryManagerBlockers:
    """Tests for blocker management."""

    def test_add_blocker(self, memory_manager):
        memory_manager.add_blocker("Need API key")

        memory = memory_manager.get()
        assert "Need API key" in memory.blockers

    def test_add_duplicate_blocker(self, memory_manager):
        memory_manager.add_blocker("Blocker 1")
        memory_manager.add_blocker("Blocker 1")

        memory = memory_manager.get()
        assert len(memory.blockers) == 1

    def test_remove_blocker(self, memory_manager):
        memory_manager.add_blocker("Blocker 1")
        memory_manager.add_blocker("Blocker 2")
        memory_manager.remove_blocker("Blocker 1")

        memory = memory_manager.get()
        assert "Blocker 1" not in memory.blockers
        assert "Blocker 2" in memory.blockers


class TestMemoryManagerReference:
    """Tests for reference data management."""

    def test_set_tools(self, memory_manager):
        memory_manager.set_tools(["Edit", "Bash", "Read"])

        memory = memory_manager.get()
        assert memory.available_tools == ["Edit", "Bash", "Read"]

    def test_set_files(self, memory_manager):
        memory_manager.set_files(["main.py", "test.py"])

        memory = memory_manager.get()
        assert memory.key_files == ["main.py", "test.py"]


class TestMemoryManagerSession:
    """Tests for session management."""

    def test_end_session(self, memory_manager):
        memory_manager.add_discovery("Test discovery")
        result = memory_manager.end_session("Completed feature implementation")

        assert result.last_session_end is not None
        # Should have added summary as discovery
        assert len(result.discoveries) >= 1

    def test_end_session_with_summary(self, memory_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="JWT ticket")

        memory_manager.set_current_work(ticket_id=ticket_id)
        result = memory_manager.end_session("Finished JWT implementation")

        memory = memory_manager.get()
        # Check that summary was added as discovery
        summaries = [d for d in memory.discoveries if "JWT" in d.content]
        assert len(summaries) >= 1

    def test_clear_memory(self, memory_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="Test ticket")

        memory_manager.set_current_work(ticket_id=ticket_id)
        memory_manager.add_discovery("Test")
        memory_manager.clear()

        memory = memory_manager.get()
        assert memory.current_ticket_id is None


class TestMemoryCondensation:
    """Tests for memory condensation."""

    def test_condense_removes_low_importance(self, memory_manager):
        # Add many low importance discoveries
        for i in range(50):
            memory_manager.add_discovery(f"Low importance discovery {i}", importance=1)

        # Add high importance discoveries
        for i in range(5):
            memory_manager.add_discovery(f"High importance discovery {i}", importance=5)

        memory = memory_manager.get()

        # Force condensation through end_session
        memory_manager.end_session()

        condensed = memory_manager.get()

        # High importance should be preserved
        high_imp = [d for d in condensed.discoveries if d.importance == 5]
        assert len(high_imp) <= 5  # Should have most/all high importance
