"""Tests for the Toon format parser/serializer."""

import pytest

from semfora_pm.toon import (
    Plan,
    PlanStep,
    AcceptanceCriterion,
    PlanNote,
    create_plan,
    serialize,
    deserialize,
    update_step_status,
    update_ac_status,
    add_note,
    add_blocker,
    get_progress_summary,
)


class TestPlanDataclass:
    """Tests for Plan dataclass."""

    def test_create_empty_plan(self):
        plan = Plan(title="Test Plan")
        assert plan.title == "Test Plan"
        assert plan.status == "draft"
        assert plan.steps == []
        assert plan.acceptance_criteria == []

    def test_create_plan_with_steps(self):
        steps = [
            PlanStep(index=1, description="Step 1"),
            PlanStep(index=2, description="Step 2"),
        ]
        plan = Plan(title="Test", steps=steps)
        assert len(plan.steps) == 2
        assert plan.steps[0].description == "Step 1"

    def test_plan_step_defaults(self):
        step = PlanStep(index=1, description="Test step")
        assert step.status == "pending"
        assert step.deviated is False
        assert step.deviation_reason is None


class TestCreatePlan:
    """Tests for create_plan function."""

    def test_create_basic_plan(self):
        plan = create_plan(title="Implement feature")
        assert plan.title == "Implement feature"
        assert plan.status == "draft"

    def test_create_plan_with_steps(self):
        plan = create_plan(
            title="Implement feature",
            steps=["Step 1", "Step 2", "Step 3"],
        )
        assert len(plan.steps) == 3
        assert plan.steps[0].index == 1
        assert plan.steps[0].description == "Step 1"
        assert plan.steps[2].index == 3

    def test_create_plan_with_acceptance_criteria(self):
        plan = create_plan(
            title="Implement feature",
            acceptance_criteria=["AC 1", "AC 2"],
        )
        assert len(plan.acceptance_criteria) == 2
        assert plan.acceptance_criteria[0].index == 0
        assert plan.acceptance_criteria[0].text == "AC 1"

    def test_create_plan_with_all_fields(self):
        plan = create_plan(
            title="Full plan",
            ticket_id="SEM-45",
            steps=["Step 1"],
            acceptance_criteria=["AC 1"],
            tools=["Edit", "Bash"],
            files=["src/main.py"],
        )
        assert plan.ticket_id == "SEM-45"
        assert plan.tools == ["Edit", "Bash"]
        assert plan.files == ["src/main.py"]


class TestSerializeDeserialize:
    """Tests for serialize/deserialize functions."""

    def test_serialize_basic_plan(self):
        plan = create_plan(title="Test plan")
        serialized = serialize(plan)
        assert isinstance(serialized, str)
        assert "Test plan" in serialized

    def test_deserialize_basic_plan(self):
        plan = create_plan(title="Test plan", steps=["Step 1"])
        serialized = serialize(plan)
        restored = deserialize(serialized)
        assert restored.title == plan.title
        assert len(restored.steps) == 1

    def test_roundtrip_full_plan(self):
        plan = create_plan(
            title="Full plan",
            ticket_id="SEM-123",
            steps=["Step 1", "Step 2"],
            acceptance_criteria=["AC 1"],
            tools=["Edit"],
            files=["main.py"],
        )
        serialized = serialize(plan)
        restored = deserialize(serialized)

        assert restored.title == plan.title
        assert restored.ticket_id == plan.ticket_id
        assert len(restored.steps) == 2
        assert len(restored.acceptance_criteria) == 1
        assert restored.tools == ["Edit"]
        assert restored.files == ["main.py"]

    def test_roundtrip_preserves_step_status(self):
        plan = create_plan(title="Test", steps=["Step 1", "Step 2"])
        plan.steps[0].status = "completed"
        plan.steps[1].status = "in_progress"

        serialized = serialize(plan)
        restored = deserialize(serialized)

        assert restored.steps[0].status == "completed"
        assert restored.steps[1].status == "in_progress"


class TestUpdateStepStatus:
    """Tests for update_step_status function."""

    def test_update_step_to_in_progress(self):
        plan = create_plan(title="Test", steps=["Step 1", "Step 2"])
        update_step_status(plan, 1, "in_progress")
        assert plan.steps[0].status == "in_progress"

    def test_update_step_to_completed(self):
        plan = create_plan(title="Test", steps=["Step 1"])
        update_step_status(plan, 1, "completed", output="Done!")
        assert plan.steps[0].status == "completed"
        assert plan.steps[0].output == "Done!"

    def test_update_step_invalid_index(self):
        plan = create_plan(title="Test", steps=["Step 1"])
        # Should not raise, just do nothing
        update_step_status(plan, 99, "completed")
        assert plan.steps[0].status == "pending"


class TestUpdateAcStatus:
    """Tests for update_ac_status function."""

    def test_update_ac_status(self):
        plan = create_plan(title="Test", acceptance_criteria=["AC 1"])
        update_ac_status(plan, 0, "verified", evidence="Test passed")
        assert plan.acceptance_criteria[0].status == "verified"
        assert plan.acceptance_criteria[0].evidence == "Test passed"

    def test_update_ac_invalid_index(self):
        plan = create_plan(title="Test", acceptance_criteria=["AC 1"])
        # Should not raise
        update_ac_status(plan, 99, "verified")
        assert plan.acceptance_criteria[0].status == "pending"


class TestAddNote:
    """Tests for add_note function."""

    def test_add_discovery_note(self):
        plan = create_plan(title="Test")
        add_note(plan, "Found existing code", note_type="discovery")
        assert len(plan.notes) == 1
        assert plan.notes[0].content == "Found existing code"
        assert plan.notes[0].note_type == "discovery"

    def test_add_multiple_notes(self):
        plan = create_plan(title="Test")
        add_note(plan, "Note 1", note_type="discovery")
        add_note(plan, "Note 2", note_type="decision")
        assert len(plan.notes) == 2


class TestAddBlocker:
    """Tests for add_blocker function."""

    def test_add_blocker_to_step(self):
        plan = create_plan(title="Test", steps=["Step 1"])
        add_blocker(plan, 1, "Waiting for API key")
        assert plan.steps[0].blocker == "Waiting for API key"

    def test_add_blocker_invalid_step(self):
        plan = create_plan(title="Test", steps=["Step 1"])
        # Should not raise
        add_blocker(plan, 99, "Blocker")
        assert plan.steps[0].blocker is None


class TestGetProgressSummary:
    """Tests for get_progress_summary function."""

    def test_empty_plan_progress(self):
        plan = create_plan(title="Test")
        progress = get_progress_summary(plan)
        assert progress["steps"]["total"] == 0
        assert progress["steps"]["completed"] == 0
        assert progress["steps"]["pending"] == 0
        assert progress["blockers"] == []

    def test_partial_progress(self):
        plan = create_plan(title="Test", steps=["Step 1", "Step 2", "Step 3"])
        plan.steps[0].status = "completed"
        plan.steps[1].status = "in_progress"

        progress = get_progress_summary(plan)
        assert progress["steps"]["total"] == 3
        assert progress["steps"]["completed"] == 1
        assert progress["steps"]["pending"] == 1
        assert progress["steps"]["in_progress"] == 1

    def test_progress_with_blockers(self):
        plan = create_plan(title="Test", steps=["Step 1"])
        plan.steps[0].blocker = "Need API key"

        progress = get_progress_summary(plan)
        assert progress["blockers"] == ["Need API key"]

    def test_progress_with_ac(self):
        plan = create_plan(title="Test", acceptance_criteria=["AC 1", "AC 2"])
        plan.acceptance_criteria[0].status = "verified"

        progress = get_progress_summary(plan)
        assert progress["acceptance_criteria"]["total"] == 2
        assert progress["acceptance_criteria"]["completed"] == 1  # counts "verified" status too
        assert progress["acceptance_criteria"]["pending"] == 1
