"""Tests for the PlanManager."""

import pytest
import uuid

from semfora_pm.db import Database
from semfora_pm.plans import PlanManager, PlanSummary
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
def plan_manager(db, project_id):
    """Create a PlanManager for testing."""
    # Create a project record first
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, config_path) VALUES (?, ?, ?)",
            (project_id, "Test Project", "/tmp/test"),
        )
    return PlanManager(db, project_id)


@pytest.fixture
def ticket_manager(db, project_id):
    """Create a TicketManager for testing."""
    return TicketManager(db, project_id)


class TestPlanManagerCreate:
    """Tests for creating plans."""

    def test_create_basic_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test plan")
        assert plan_id is not None
        assert len(plan_id) == 36  # UUID format

    def test_create_plan_with_steps(self, plan_manager):
        plan_id = plan_manager.create(
            title="Plan with steps",
            steps=["Step 1", "Step 2", "Step 3"],
        )

        plan = plan_manager.get(plan_id)
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "Step 1"

    def test_create_plan_with_ticket(self, plan_manager, ticket_manager):
        # Create a ticket first
        ticket_id = ticket_manager.create(title="Test ticket")

        plan_id = plan_manager.create(
            title="Ticket plan",
            ticket_id=ticket_id,
        )

        plan = plan_manager.get(plan_id)
        assert plan.ticket_id == ticket_id

    def test_create_plan_with_all_options(self, plan_manager, ticket_manager):
        # Create a ticket first
        ticket_id = ticket_manager.create(title="Test ticket")

        plan_id = plan_manager.create(
            title="Full plan",
            ticket_id=ticket_id,
            steps=["Step 1"],
            acceptance_criteria=["AC 1"],
            tools=["Edit", "Bash"],
            files=["main.py", "test.py"],
        )

        plan = plan_manager.get(plan_id)
        assert plan.title == "Full plan"
        assert plan.ticket_id == ticket_id
        assert len(plan.steps) == 1
        assert len(plan.acceptance_criteria) == 1
        assert plan.tools == ["Edit", "Bash"]
        assert plan.files == ["main.py", "test.py"]

    def test_created_plan_has_draft_status(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        plan = plan_manager.get(plan_id)
        assert plan.status == "draft"


class TestPlanManagerGet:
    """Tests for getting plans."""

    def test_get_existing_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test plan")
        plan = plan_manager.get(plan_id)
        assert plan is not None
        assert plan.title == "Test plan"

    def test_get_nonexistent_plan(self, plan_manager):
        plan = plan_manager.get("nonexistent-id")
        assert plan is None


class TestPlanManagerList:
    """Tests for listing plans."""

    def test_list_all_plans(self, plan_manager):
        plan_manager.create(title="Plan 1")
        plan_manager.create(title="Plan 2")
        plan_manager.create(title="Plan 3")

        plans = plan_manager.list()
        assert len(plans) == 3

    def test_list_by_ticket(self, plan_manager, ticket_manager):
        # Create tickets first
        ticket_id_1 = ticket_manager.create(title="Ticket 1")
        ticket_id_2 = ticket_manager.create(title="Ticket 2")

        plan_manager.create(title="Plan 1", ticket_id=ticket_id_1)
        plan_manager.create(title="Plan 2", ticket_id=ticket_id_1)
        plan_manager.create(title="Plan 3", ticket_id=ticket_id_2)

        plans = plan_manager.list(ticket_id=ticket_id_1)
        assert len(plans) == 2

    def test_list_by_status(self, plan_manager):
        plan_id = plan_manager.create(title="Plan 1")
        plan_manager.create(title="Plan 2")
        plan_manager.activate(plan_id)

        active_plans = plan_manager.list(status="active")
        assert len(active_plans) == 1
        assert active_plans[0].title == "Plan 1"

    def test_list_with_limit(self, plan_manager):
        for i in range(10):
            plan_manager.create(title=f"Plan {i}")

        plans = plan_manager.list(limit=5)
        assert len(plans) == 5

    def test_list_returns_plan_summary(self, plan_manager):
        plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        plans = plan_manager.list()

        assert len(plans) == 1
        assert isinstance(plans[0], PlanSummary)
        assert plans[0].step_count == 2
        assert plans[0].completed_steps == 0


class TestPlanManagerActivate:
    """Tests for activating plans."""

    def test_activate_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        result = plan_manager.activate(plan_id)

        assert result is True
        plan = plan_manager.get(plan_id)
        assert plan.status == "active"

    def test_activate_pauses_other_active_plans(self, plan_manager):
        plan1_id = plan_manager.create(title="Plan 1")
        plan2_id = plan_manager.create(title="Plan 2")

        plan_manager.activate(plan1_id)
        plan_manager.activate(plan2_id)

        plan1 = plan_manager.get(plan1_id)
        plan2 = plan_manager.get(plan2_id)

        assert plan1.status == "paused"
        assert plan2.status == "active"

    def test_activate_nonexistent_plan(self, plan_manager):
        result = plan_manager.activate("nonexistent-id")
        assert result is False

    def test_get_active_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Active plan")
        plan_manager.activate(plan_id)

        active = plan_manager.get_active()
        assert active is not None
        active_id, active_plan = active
        assert active_id == plan_id
        assert active_plan.title == "Active plan"


class TestPlanManagerComplete:
    """Tests for completing plans."""

    def test_complete_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        result = plan_manager.complete(plan_id)

        assert result is True
        plan = plan_manager.get(plan_id)
        assert plan.status == "completed"

    def test_complete_nonexistent_plan(self, plan_manager):
        result = plan_manager.complete("nonexistent-id")
        assert result is False


class TestPlanManagerAbandon:
    """Tests for abandoning plans."""

    def test_abandon_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        result = plan_manager.abandon(plan_id, "Changed approach")

        assert result is True
        plan = plan_manager.get(plan_id)
        assert plan.status == "abandoned"


class TestPlanStepManagement:
    """Tests for step management."""

    def test_get_steps(self, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        steps = plan_manager.get_steps(plan_id)

        assert len(steps) == 2
        assert steps[0].description == "Step 1"
        assert steps[0].order_index == 1

    def test_start_step(self, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        steps = plan_manager.get_steps(plan_id)

        result = plan_manager.start_step(steps[0].id)
        assert result is True

        updated_steps = plan_manager.get_steps(plan_id)
        assert updated_steps[0].status == "in_progress"

    def test_complete_step(self, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        steps = plan_manager.get_steps(plan_id)

        result = plan_manager.complete_step(steps[0].id, "Step completed!")
        assert result is True

        updated_steps = plan_manager.get_steps(plan_id)
        assert updated_steps[0].status == "completed"

    def test_skip_step(self, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        steps = plan_manager.get_steps(plan_id)

        result = plan_manager.skip_step(steps[0].id, "Not needed", approved=True)
        assert result is True

        updated_steps = plan_manager.get_steps(plan_id)
        assert updated_steps[0].status == "skipped"
        assert updated_steps[0].deviated is True
        assert updated_steps[0].deviation_reason == "Not needed"
        assert updated_steps[0].deviation_approved is True

    def test_add_step(self, plan_manager):
        plan_id = plan_manager.create(title="Test", steps=["Step 1"])
        step_id = plan_manager.add_step(plan_id, "Step 2")

        assert step_id is not None
        steps = plan_manager.get_steps(plan_id)
        assert len(steps) == 2
        assert steps[1].description == "Step 2"
        assert steps[1].order_index == 2

    def test_step_completion_syncs_to_toon(self, plan_manager):
        """Verify that completing a step updates the TOON content."""
        plan_id = plan_manager.create(title="Test", steps=["Step 1", "Step 2"])
        steps = plan_manager.get_steps(plan_id)

        plan_manager.complete_step(steps[0].id)

        plan = plan_manager.get(plan_id)
        assert plan.steps[0].status == "completed"
        assert plan.steps[1].status == "pending"


class TestPlanSearch:
    """Tests for searching plans."""

    def test_search_by_title(self, plan_manager):
        plan_manager.create(title="Implement JWT authentication")
        plan_manager.create(title="Add user login")
        plan_manager.create(title="Fix JWT bug")

        results = plan_manager.search("JWT")
        assert len(results) == 2

    def test_search_empty_query(self, plan_manager):
        plan_manager.create(title="Test plan")
        results = plan_manager.search("")
        assert len(results) == 0

    def test_search_no_results(self, plan_manager):
        plan_manager.create(title="Test plan")
        results = plan_manager.search("nonexistent")
        assert len(results) == 0


class TestPlanManagerUpdate:
    """Tests for updating plan metadata."""

    def test_update_title(self, plan_manager):
        plan_id = plan_manager.create(title="Original title")
        plan = plan_manager.update(plan_id, title="New title")

        assert plan is not None
        assert plan.title == "New title"

    def test_update_link_ticket(self, plan_manager, ticket_manager):
        # Create plan without ticket
        plan_id = plan_manager.create(title="Ad-hoc plan")
        plan = plan_manager.get(plan_id)
        assert plan.ticket_id is None

        # Create ticket and link retroactively
        ticket_id = ticket_manager.create(title="New ticket")
        plan = plan_manager.update(plan_id, ticket_id=ticket_id)

        assert plan.ticket_id == ticket_id

    def test_update_unlink_ticket(self, plan_manager, ticket_manager):
        # Create plan with ticket
        ticket_id = ticket_manager.create(title="Test ticket")
        plan_id = plan_manager.create(title="Linked plan", ticket_id=ticket_id)

        # Unlink by passing empty string
        plan = plan_manager.update(plan_id, ticket_id="")
        assert plan.ticket_id is None

    def test_update_tools(self, plan_manager):
        plan_id = plan_manager.create(title="Test", tools=["Read"])
        plan = plan_manager.update(plan_id, tools=["Read", "Edit", "Bash"])

        assert plan.tools == ["Read", "Edit", "Bash"]

    def test_update_files(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        plan = plan_manager.update(plan_id, files=["main.py", "test.py"])

        assert plan.files == ["main.py", "test.py"]

    def test_update_nonexistent_returns_none(self, plan_manager):
        plan = plan_manager.update("nonexistent-id", title="New title")
        # Returns None because the plan doesn't exist
        assert plan is None

    def test_update_no_changes_returns_plan(self, plan_manager):
        plan_id = plan_manager.create(title="Test")
        plan = plan_manager.update(plan_id)

        assert plan is not None
        assert plan.title == "Test"
