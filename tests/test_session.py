"""Tests for the SessionManager."""

import pytest
import uuid

from semfora_pm.db import Database
from semfora_pm.session import SessionManager, SessionContext, SessionSummary
from semfora_pm.plans import PlanManager
from semfora_pm.memory import MemoryManager
from semfora_pm.tickets import TicketManager


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
def session_manager(db, project_id):
    """Create a SessionManager for testing."""
    # Create a project record first
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
            (project_id, "Test Project", "/tmp/test"),
        )
    return SessionManager(db, project_id)


@pytest.fixture
def plan_manager(db, project_id):
    """Create a PlanManager for testing."""
    return PlanManager(db, project_id)


@pytest.fixture
def memory_manager(db, project_id):
    """Create a MemoryManager for testing."""
    return MemoryManager(db, project_id)


@pytest.fixture
def ticket_manager(db, project_id):
    """Create a TicketManager for testing."""
    return TicketManager(db, project_id)


class TestSessionContext:
    """Tests for SessionContext dataclass."""

    def test_empty_context(self):
        from semfora_pm.memory import ProjectMemory
        memory = ProjectMemory()
        context = SessionContext(memory=memory)
        assert context.current_plan is None
        assert context.has_active_work is False
        assert context.suggestions == []

    def test_context_with_work(self):
        from semfora_pm.memory import ProjectMemory
        from semfora_pm.toon import create_plan

        memory = ProjectMemory()
        plan = create_plan(title="Test plan")

        context = SessionContext(
            memory=memory,
            current_plan=plan,
            current_plan_id="plan-123",
            has_active_work=True,
        )
        assert context.has_active_work is True
        assert context.current_plan.title == "Test plan"


class TestSessionSummary:
    """Tests for SessionSummary dataclass."""

    def test_empty_summary(self):
        summary = SessionSummary()
        assert summary.steps_completed == 0
        assert summary.blockers == []

    def test_summary_with_progress(self):
        summary = SessionSummary(
            steps_completed=3,
            steps_remaining=2,
            blockers=["Need API key"],
            next_step="Add authentication",
        )
        assert summary.steps_completed == 3
        assert summary.steps_remaining == 2
        assert "Need API key" in summary.blockers


class TestSessionManagerStart:
    """Tests for session start."""

    def test_start_empty_session(self, session_manager):
        context = session_manager.start()
        assert isinstance(context, SessionContext)
        assert context.has_active_work is False

    def test_start_with_ticket(self, session_manager, plan_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="Auth ticket")

        # Create a plan for that ticket
        plan_manager.create(title="Auth plan", ticket_id=ticket_id)

        context = session_manager.start(ticket_id=ticket_id)
        assert len(context.matching_plans) == 1
        assert context.matching_plans[0].title == "Auth plan"

    def test_start_with_query(self, session_manager, plan_manager):
        plan_manager.create(title="Implement JWT authentication")
        plan_manager.create(title="Add user login")

        context = session_manager.start(query="JWT")
        assert len(context.matching_plans) >= 1

    def test_start_with_active_plan(self, session_manager, plan_manager):
        plan_id = plan_manager.create(title="Active plan", steps=["Step 1"])
        plan_manager.activate(plan_id)

        context = session_manager.start()
        assert context.has_active_work is True
        assert context.current_plan is not None
        assert context.current_plan.title == "Active plan"


class TestSessionManagerContinue:
    """Tests for session continue."""

    def test_continue_no_active_plan(self, session_manager):
        context = session_manager.continue_session()
        assert context.has_active_work is False
        assert "No active plan found" in context.suggestions[0]

    def test_continue_with_active_plan(self, session_manager, plan_manager, memory_manager):
        # Create and activate a plan
        plan_id = plan_manager.create(title="Test plan", steps=["Step 1", "Step 2"])
        plan_manager.activate(plan_id)

        # Set in memory
        memory_manager.set_current_work(plan_id=plan_id)

        context = session_manager.continue_session()
        assert context.has_active_work is True
        assert context.current_plan_id == plan_id

    def test_continue_finds_current_step(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        plan_manager.activate(plan_id)
        memory_manager.set_current_work(plan_id=plan_id)

        context = session_manager.continue_session()
        # Should mention next step
        assert any("Step" in s for s in context.suggestions)


class TestSessionManagerEnd:
    """Tests for session end."""

    def test_end_empty_session(self, session_manager):
        summary = session_manager.end()
        assert isinstance(summary, SessionSummary)
        assert summary.steps_completed == 0

    def test_end_with_summary(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        plan_manager.activate(plan_id)
        memory_manager.set_current_work(plan_id=plan_id)

        summary = session_manager.end(summary="Completed authentication")
        assert isinstance(summary, SessionSummary)

    def test_end_completes_plan_when_done(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        plan_manager.activate(plan_id)

        # Complete the step
        steps = plan_manager.get_steps(plan_id)
        plan_manager.complete_step(steps[0].id)

        memory_manager.set_current_work(plan_id=plan_id)

        summary = session_manager.end(outcome="success")
        assert summary.plan_status == "completed"

    def test_end_abandons_plan(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test")
        plan_manager.activate(plan_id)
        memory_manager.set_current_work(plan_id=plan_id)

        summary = session_manager.end(outcome="abandoned", summary="Changed approach")
        assert summary.plan_status == "abandoned"


class TestSessionManagerActivatePlan:
    """Tests for plan activation."""

    def test_activate_plan(self, session_manager, plan_manager):
        plan_id = plan_manager.create(title="Test plan")
        plan = session_manager.activate_plan(plan_id)

        assert plan is not None
        assert plan.status == "active"

    def test_activate_updates_memory(self, session_manager, plan_manager, memory_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="Test ticket")
        plan_id = plan_manager.create(title="Test plan", ticket_id=ticket_id)
        session_manager.activate_plan(plan_id)

        memory = memory_manager.get()
        assert memory.current_plan_id == plan_id

    def test_activate_nonexistent_plan(self, session_manager):
        plan = session_manager.activate_plan("nonexistent-id")
        assert plan is None


class TestSessionManagerCreateAndActivate:
    """Tests for create and activate."""

    def test_create_and_activate(self, session_manager):
        plan_id, plan = session_manager.create_and_activate_plan(
            title="New plan",
            steps=["Step 1", "Step 2"],
        )

        assert plan_id is not None
        assert plan.title == "New plan"
        assert plan.status == "active"

    def test_create_and_activate_with_ticket(self, session_manager, memory_manager, ticket_manager):
        # Create a real ticket (FK constraint requires valid ticket ID)
        ticket_id = ticket_manager.create(title="Test ticket")

        plan_id, plan = session_manager.create_and_activate_plan(
            title="Ticket plan",
            ticket_id=ticket_id,
        )

        memory = memory_manager.get()
        # Memory should reference the plan
        assert memory.current_plan_id == plan_id


class TestSessionManagerStepTracking:
    """Tests for step tracking."""

    def test_record_step_complete(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        session_manager.activate_plan(plan_id)

        session_manager.record_step_complete(1, "Done!")

        steps = plan_manager.get_steps(plan_id)
        assert steps[0].status == "completed"

    def test_record_step_updates_memory(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        session_manager.activate_plan(plan_id)

        session_manager.record_step_complete(1)

        memory = memory_manager.get()
        assert memory.completed_steps == 1


class TestSessionManagerDeviation:
    """Tests for deviation tracking."""

    def test_record_deviation(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        session_manager.activate_plan(plan_id)

        session_manager.record_deviation(1, "Found better approach", approved=True)

        steps = plan_manager.get_steps(plan_id)
        assert steps[0].status == "skipped"
        assert steps[0].deviated is True

    def test_deviation_adds_discovery(self, session_manager, plan_manager, memory_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        session_manager.activate_plan(plan_id)

        session_manager.record_deviation(1, "Better approach found")

        memory = memory_manager.get()
        assert len(memory.discoveries) >= 1
        assert any("Deviation" in d.content for d in memory.discoveries)


class TestSessionManagerDiscoveries:
    """Tests for discovery management."""

    def test_add_discovery(self, session_manager, memory_manager):
        session_manager.add_discovery("Found existing pattern", importance=3)

        memory = memory_manager.get()
        assert len(memory.discoveries) == 1
        assert memory.discoveries[0].content == "Found existing pattern"


class TestSessionManagerBlockers:
    """Tests for blocker management."""

    def test_add_blocker(self, session_manager, memory_manager):
        session_manager.add_blocker("Need API key")

        memory = memory_manager.get()
        assert "Need API key" in memory.blockers

    def test_resolve_blocker(self, session_manager, memory_manager):
        session_manager.add_blocker("Blocker 1")
        session_manager.add_blocker("Blocker 2")
        session_manager.resolve_blocker("Blocker 1")

        memory = memory_manager.get()
        assert "Blocker 1" not in memory.blockers
        assert "Blocker 2" in memory.blockers


class TestSessionManagerStatus:
    """Tests for session status."""

    def test_get_empty_status(self, session_manager):
        status = session_manager.get_status()
        assert "has_memory" in status
        assert status["current_plan"] is None

    def test_get_status_with_plan(self, session_manager, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        plan_manager.activate(plan_id)

        status = session_manager.get_status()
        assert "active_plan" in status
        assert status["active_plan"]["title"] == "Test"

    def test_get_status_with_blockers(self, session_manager, memory_manager):
        memory_manager.add_blocker("Blocker 1")

        status = session_manager.get_status()
        assert "Blocker 1" in status["blockers"]


class TestSessionManagerSuggestNextWork:
    """Tests for suggest_next_work feature."""

    def test_suggest_no_active_work(self, session_manager):
        result = session_manager.suggest_next_work()
        assert result["blocked"] == []
        assert result["ready"] == []
        assert result["recommended"] is None
        assert result["summary"] == "No active work"

    def test_suggest_with_ready_plan(self, session_manager, plan_manager):
        plan_id = plan_manager.create(title="Test plan", steps=["Step 1"])
        plan_manager.activate(plan_id)

        result = session_manager.suggest_next_work()
        assert len(result["ready"]) == 1
        assert result["recommended"] is not None
        assert result["recommended"].plan_title == "Test plan"

    def test_suggest_with_blocked_plan(self, session_manager, plan_manager):
        plan_id = plan_manager.create(title="Blocked plan", steps=["Step 1"])
        plan_manager.activate(plan_id)

        # Add a blocker via the plan
        plan = plan_manager.get(plan_id)
        plan.steps[0].blocker = "Waiting for API"
        plan_manager.update_content(plan_id, plan)

        result = session_manager.suggest_next_work()
        assert len(result["blocked"]) == 1
        assert result["blocked"][0].reason.startswith("Blocked:")

    def test_suggest_prioritizes_by_ticket_priority(self, session_manager, plan_manager, ticket_manager):
        # Create tickets with different priorities
        low_ticket = ticket_manager.create(title="Low priority", priority=1)
        high_ticket = ticket_manager.create(title="High priority", priority=4)

        # Create plans linked to tickets
        plan_manager.create(title="Low plan", ticket_id=low_ticket, steps=["Step 1"])
        high_plan_id = plan_manager.create(title="High plan", ticket_id=high_ticket, steps=["Step 1"])

        # Activate both (second will pause first but both show in list)
        plan_manager.activate(high_plan_id)

        result = session_manager.suggest_next_work()
        # High priority should be recommended
        assert result["recommended"].plan_title == "High plan"

    def test_suggest_multiple_plans(self, session_manager, plan_manager):
        plan1_id = plan_manager.create(title="Plan 1", steps=["Step 1", "Step 2"])
        plan2_id = plan_manager.create(title="Plan 2", steps=["Step 1"])

        plan_manager.activate(plan1_id)
        plan_manager.activate(plan2_id)  # Pauses plan1

        result = session_manager.suggest_next_work()
        assert len(result["ready"]) == 2
        assert result["recommended"] is not None


class TestSessionManagerQuickFix:
    """Tests for quick_fix_note feature."""

    def test_quick_fix_note(self, session_manager, memory_manager):
        session_manager.quick_fix_note("Fixed null pointer in LoginForm")

        memory = memory_manager.get()
        assert len(memory.discoveries) == 1
        assert "Quick fix:" in memory.discoveries[0].content
        assert "LoginForm" in memory.discoveries[0].content

    def test_quick_fix_with_importance(self, session_manager, memory_manager):
        session_manager.quick_fix_note("Critical security fix", importance=5)

        memory = memory_manager.get()
        assert memory.discoveries[0].importance == 5
