"""Plan data structures with TOON format serialization.

Uses the toon-python library (https://github.com/toon-format/toon-python)
for compact, token-efficient serialization of plan data.

TOON (Token-Oriented Object Notation) reduces token costs by 30-60% vs JSON,
making it ideal for storing plans that will be loaded into LLM context.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Any

try:
    from toon_format import encode, decode
except ImportError:
    # Fallback to JSON if toon-python not installed
    import json
    def encode(obj: Any) -> str:
        return json.dumps(obj, indent=2)
    def decode(s: str) -> Any:
        return json.loads(s)


class StepStatus(Enum):
    """Status of a plan step or acceptance criterion."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class NoteType(Enum):
    """Type of note entry."""
    DISCOVERY = "discovery"
    BLOCKER = "blocker"
    DEVIATION = "deviation"
    COMMENT = "comment"


@dataclass
class PlanStep:
    """A step in a plan."""
    index: int
    description: str
    status: str = "pending"  # Use string for easy serialization
    output: Optional[str] = None
    blocker: Optional[str] = None
    deviated: bool = False
    deviation_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        d = {"i": self.index, "d": self.description, "s": self.status[0]}  # Compact keys
        if self.output:
            d["o"] = self.output
        if self.blocker:
            d["b"] = self.blocker
        if self.deviated:
            d["dv"] = True
            if self.deviation_reason:
                d["dr"] = self.deviation_reason
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        """Create from dict."""
        status_map = {"p": "pending", "i": "in_progress", "c": "completed", "s": "skipped"}
        return cls(
            index=d.get("i", d.get("index", 0)),
            description=d.get("d", d.get("description", "")),
            status=status_map.get(d.get("s", "p"), d.get("status", "pending")),
            output=d.get("o", d.get("output")),
            blocker=d.get("b", d.get("blocker")),
            deviated=d.get("dv", d.get("deviated", False)),
            deviation_reason=d.get("dr", d.get("deviation_reason")),
        )


@dataclass
class AcceptanceCriterion:
    """An acceptance criterion."""
    index: int
    text: str
    status: str = "pending"
    evidence: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        d = {"i": self.index, "t": self.text, "s": self.status[0]}
        if self.evidence:
            d["e"] = self.evidence
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AcceptanceCriterion":
        """Create from dict."""
        status_map = {"p": "pending", "i": "in_progress", "c": "completed", "v": "verified", "f": "failed"}
        return cls(
            index=d.get("i", d.get("index", 0)),
            text=d.get("t", d.get("text", "")),
            status=status_map.get(d.get("s", "p"), d.get("status", "pending")),
            evidence=d.get("e", d.get("evidence")),
        )


@dataclass
class PlanNote:
    """A note entry (discovery, blocker, deviation, or comment)."""
    note_type: str  # discovery, blocker, deviation, comment
    content: str

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        type_map = {"discovery": "d", "blocker": "b", "deviation": "v", "comment": "c"}
        return {"t": type_map.get(self.note_type, "c"), "c": self.content}

    @classmethod
    def from_dict(cls, d: dict) -> "PlanNote":
        """Create from dict."""
        type_map = {"d": "discovery", "b": "blocker", "v": "deviation", "c": "comment"}
        return cls(
            note_type=type_map.get(d.get("t", "c"), d.get("note_type", "comment")),
            content=d.get("c", d.get("content", "")),
        )


@dataclass
class Plan:
    """A plan for implementing a ticket.

    Plans are the foundation of agent memory - they track HOW to accomplish
    a ticket, including steps, progress, blockers, and discoveries.
    """
    # Metadata
    title: str = ""
    ticket_id: Optional[str] = None  # e.g., "SEM-45" or internal UUID
    status: str = "draft"  # draft, active, paused, completed, abandoned
    created: Optional[str] = None

    # Content
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    notes: list[PlanNote] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for TOON serialization."""
        d = {
            "title": self.title,
            "status": self.status,
        }
        if self.ticket_id:
            d["ticket"] = self.ticket_id
        if self.created:
            d["created"] = self.created

        if self.acceptance_criteria:
            d["ac"] = [ac.to_dict() for ac in self.acceptance_criteria]
        if self.steps:
            d["steps"] = [s.to_dict() for s in self.steps]
        if self.tools:
            d["tools"] = self.tools
        if self.files:
            d["files"] = self.files
        if self.notes:
            d["notes"] = [n.to_dict() for n in self.notes]

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        """Create from dict (after TOON decode)."""
        return cls(
            title=d.get("title", ""),
            ticket_id=d.get("ticket"),
            status=d.get("status", "draft"),
            created=d.get("created"),
            acceptance_criteria=[AcceptanceCriterion.from_dict(ac) for ac in d.get("ac", [])],
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            tools=d.get("tools", []),
            files=d.get("files", []),
            notes=[PlanNote.from_dict(n) for n in d.get("notes", [])],
        )


def serialize(plan: Plan) -> str:
    """Serialize a Plan to TOON format.

    Args:
        plan: Plan object to serialize

    Returns:
        TOON format string (compact, token-efficient)
    """
    return encode(plan.to_dict())


def deserialize(content: str) -> Plan:
    """Deserialize TOON format content into a Plan.

    Args:
        content: TOON format string

    Returns:
        Parsed Plan object
    """
    data = decode(content)
    return Plan.from_dict(data)


def create_plan(
    title: str,
    ticket_id: Optional[str] = None,
    steps: Optional[list[str]] = None,
    acceptance_criteria: Optional[list[str]] = None,
    tools: Optional[list[str]] = None,
    files: Optional[list[str]] = None,
) -> Plan:
    """Create a new Plan with sensible defaults.

    Args:
        title: Plan title
        ticket_id: Optional ticket ID (e.g., "SEM-45")
        steps: Optional list of step descriptions
        acceptance_criteria: Optional list of AC text
        tools: Optional list of tool names
        files: Optional list of file paths

    Returns:
        New Plan
    """
    plan = Plan(
        title=title,
        ticket_id=ticket_id,
        status="draft",
        created=datetime.utcnow().strftime("%Y-%m-%d"),
    )

    if acceptance_criteria:
        for i, text in enumerate(acceptance_criteria):
            plan.acceptance_criteria.append(AcceptanceCriterion(index=i, text=text))

    if steps:
        for i, desc in enumerate(steps, start=1):
            plan.steps.append(PlanStep(index=i, description=desc))

    if tools:
        plan.tools = tools

    if files:
        plan.files = files

    return plan


def update_step_status(plan: Plan, step_index: int, status: str, output: Optional[str] = None) -> bool:
    """Update the status of a step by index.

    Args:
        plan: Plan to modify
        step_index: Step index (1-based)
        status: New status (pending, in_progress, completed, skipped)
        output: Optional output/result from completing this step

    Returns:
        True if step was found and updated, False otherwise
    """
    for step in plan.steps:
        if step.index == step_index:
            step.status = status
            if output:
                step.output = output
            return True
    return False


def update_ac_status(plan: Plan, ac_index: int, status: str, evidence: Optional[str] = None) -> bool:
    """Update the status of an acceptance criterion by index.

    Args:
        plan: Plan to modify
        ac_index: AC index (0-based)
        status: New status (pending, in_progress, completed, verified, failed)
        evidence: Optional evidence of completion

    Returns:
        True if AC was found and updated, False otherwise
    """
    for ac in plan.acceptance_criteria:
        if ac.index == ac_index:
            ac.status = status
            if evidence:
                ac.evidence = evidence
            return True
    return False


def add_note(plan: Plan, content: str, note_type: str = "discovery") -> None:
    """Add a note to the plan.

    Args:
        plan: Plan to modify
        content: Note content
        note_type: Type of note (discovery, blocker, deviation, comment)
    """
    plan.notes.append(PlanNote(note_type=note_type, content=content))


def add_blocker(plan: Plan, step_index: int, blocker: str) -> bool:
    """Add a blocker to a step.

    Args:
        plan: Plan to modify
        step_index: Step index (1-based)
        blocker: Blocker description

    Returns:
        True if step was found and blocker added, False otherwise
    """
    for step in plan.steps:
        if step.index == step_index:
            step.blocker = blocker
            step.status = "in_progress"
            return True
    return False


def mark_deviation(plan: Plan, step_index: int, reason: str) -> bool:
    """Mark a step as deviated from the original plan.

    Args:
        plan: Plan to modify
        step_index: Step index (1-based)
        reason: Why the deviation occurred

    Returns:
        True if step was found and marked, False otherwise
    """
    for step in plan.steps:
        if step.index == step_index:
            step.deviated = True
            step.deviation_reason = reason
            return True
    return False


def get_progress_summary(plan: Plan) -> dict:
    """Get a summary of plan progress.

    Args:
        plan: Plan to analyze

    Returns:
        Dict with progress stats
    """
    total_steps = len(plan.steps)
    completed_steps = sum(1 for s in plan.steps if s.status == "completed")
    in_progress_steps = sum(1 for s in plan.steps if s.status == "in_progress")
    blocked_steps = sum(1 for s in plan.steps if s.blocker)
    deviated_steps = sum(1 for s in plan.steps if s.deviated)

    total_ac = len(plan.acceptance_criteria)
    completed_ac = sum(1 for ac in plan.acceptance_criteria if ac.status in ("completed", "verified"))

    return {
        "steps": {
            "total": total_steps,
            "completed": completed_steps,
            "in_progress": in_progress_steps,
            "blocked": blocked_steps,
            "deviated": deviated_steps,
            "pending": total_steps - completed_steps - in_progress_steps,
        },
        "acceptance_criteria": {
            "total": total_ac,
            "completed": completed_ac,
            "pending": total_ac - completed_ac,
        },
        "percent_complete": (completed_steps / total_steps * 100) if total_steps > 0 else 0,
        "blockers": [s.blocker for s in plan.steps if s.blocker],
        "discoveries": [n.content for n in plan.notes if n.note_type == "discovery"],
        "deviations": [
            {"step": s.index, "reason": s.deviation_reason}
            for s in plan.steps if s.deviated
        ],
    }


def get_current_step(plan: Plan) -> Optional[PlanStep]:
    """Get the current in-progress step, or the next pending step.

    Args:
        plan: Plan to check

    Returns:
        Current/next step, or None if all completed
    """
    # First check for in-progress
    for step in plan.steps:
        if step.status == "in_progress":
            return step

    # Then find first pending
    for step in plan.steps:
        if step.status == "pending":
            return step

    return None
