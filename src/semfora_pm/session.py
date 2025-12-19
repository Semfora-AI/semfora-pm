"""Session management for agent continuity.

Sessions provide the workflow for:
- Starting work (loading memory, finding relevant plans)
- Continuing work (resuming active plan)
- Ending work (condensing memory, updating state)

The session is the bridge between the agent and the Plans-as-Memory architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from .db import Database
from .memory import MemoryManager, ProjectMemory
from .plans import PlanManager, PlanSummary
from .tickets import TicketManager
from .toon import Plan, serialize, get_progress_summary


@dataclass
class WorkSuggestion:
    """A suggested item to work on next."""
    plan_id: str
    plan_title: str
    ticket_id: Optional[str]
    ticket_title: Optional[str]
    priority: int  # 0-4, higher = more important
    progress: str  # e.g., "2/5 steps"
    status: str  # active, paused
    reason: str  # Why this is suggested


@dataclass
class SessionContext:
    """Context returned when starting or continuing a session."""
    # Memory
    memory: ProjectMemory

    # Current work
    current_plan: Optional[Plan] = None
    current_plan_id: Optional[str] = None
    current_ticket_id: Optional[str] = None

    # Related plans
    matching_plans: list[PlanSummary] = field(default_factory=list)

    # Reference
    tools_available: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)

    # Status
    has_active_work: bool = False
    suggestions: list[str] = field(default_factory=list)


@dataclass
class SessionSummary:
    """Summary returned when ending a session."""
    # What was accomplished
    steps_completed: int = 0
    steps_remaining: int = 0
    blockers: list[str] = field(default_factory=list)
    discoveries_added: int = 0

    # Next session hints
    next_step: Optional[str] = None
    plan_status: Optional[str] = None


class SessionManager:
    """Manages agent sessions for project continuity."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the session manager.

        Args:
            db: Database connection
            project_id: Project ID
        """
        self.db = db
        self.project_id = project_id
        self.memory_mgr = MemoryManager(db, project_id)
        self.plan_mgr = PlanManager(db, project_id)
        self.ticket_mgr = TicketManager(db, project_id)

    def start(self, ticket_id: Optional[str] = None, query: Optional[str] = None) -> SessionContext:
        """Start a new session.

        If ticket_id is provided, looks for plans related to that ticket.
        If query is provided, searches for matching plans.
        Otherwise, returns the current state from memory.

        Args:
            ticket_id: Optional ticket to work on
            query: Optional search query for finding relevant plans

        Returns:
            SessionContext with memory, plans, and suggestions
        """
        memory = self.memory_mgr.get()
        context = SessionContext(
            memory=memory,
            tools_available=memory.available_tools,
            key_files=memory.key_files,
        )

        # Check for active plan
        active = self.plan_mgr.get_active()
        if active:
            plan_id, plan = active
            context.current_plan = plan
            context.current_plan_id = plan_id
            context.current_ticket_id = plan.ticket_id
            context.has_active_work = True

            progress = get_progress_summary(plan)
            context.suggestions.append(
                f"Active plan: {plan.title} ({progress['steps']['completed']}/{progress['steps']['total']} steps)"
            )
            if progress["blockers"]:
                context.suggestions.append(f"Blockers: {', '.join(progress['blockers'])}")

        # Find relevant plans
        if ticket_id:
            context.matching_plans = self.plan_mgr.list(ticket_id=ticket_id, limit=5)
            if not context.current_plan and context.matching_plans:
                context.suggestions.append(
                    f"Found {len(context.matching_plans)} plan(s) for ticket {ticket_id}"
                )
        elif query:
            context.matching_plans = self.plan_mgr.search(query, limit=5)
            if context.matching_plans:
                context.suggestions.append(
                    f"Found {len(context.matching_plans)} plan(s) matching '{query}'"
                )

        # Add memory-based suggestions
        if memory.current_step:
            context.suggestions.append(f"Last step: {memory.current_step}")
        if memory.blockers:
            context.suggestions.append(f"Known blockers: {', '.join(memory.blockers)}")

        return context

    def continue_session(self) -> SessionContext:
        """Continue from the last active plan.

        This is the "continue" command - resume exactly where you left off.

        Returns:
            SessionContext with the last active plan loaded
        """
        memory = self.memory_mgr.get()
        context = SessionContext(
            memory=memory,
            tools_available=memory.available_tools,
            key_files=memory.key_files,
        )

        # Try to load the plan from memory
        if memory.current_plan_id:
            plan = self.plan_mgr.get(memory.current_plan_id)
            if plan:
                context.current_plan = plan
                context.current_plan_id = memory.current_plan_id
                context.current_ticket_id = plan.ticket_id
                context.has_active_work = True

                progress = get_progress_summary(plan)
                context.suggestions.append(
                    f"Resuming: {plan.title} ({progress['steps']['completed']}/{progress['steps']['total']} steps)"
                )

                # Find current step
                for step in plan.steps:
                    if step.status == "in_progress":
                        context.suggestions.append(f"Current step: {step.description}")
                        break
                    elif step.status == "pending":
                        context.suggestions.append(f"Next step: {step.description}")
                        break

                if progress["blockers"]:
                    context.suggestions.append(f"Blockers: {', '.join(progress['blockers'])}")

                return context

        # No plan to continue - check for any active plan
        active = self.plan_mgr.get_active()
        if active:
            plan_id, plan = active
            context.current_plan = plan
            context.current_plan_id = plan_id
            context.current_ticket_id = plan.ticket_id
            context.has_active_work = True
            context.suggestions.append(f"Found active plan: {plan.title}")
        else:
            context.suggestions.append("No active plan found. Start a new task or select a plan to resume.")

        return context

    def end(self, summary: Optional[str] = None, outcome: str = "success") -> SessionSummary:
        """End the current session.

        Condenses memory, updates plan status if needed, and returns a summary.

        Args:
            summary: Optional summary of what was accomplished
            outcome: "success", "blocked", "abandoned"

        Returns:
            SessionSummary with progress info
        """
        result = SessionSummary()
        memory = self.memory_mgr.get()

        # Get current plan progress
        if memory.current_plan_id:
            plan = self.plan_mgr.get(memory.current_plan_id)
            if plan:
                progress = get_progress_summary(plan)
                result.steps_completed = progress["steps"]["completed"]
                result.steps_remaining = progress["steps"]["pending"]
                result.blockers = progress["blockers"]
                result.plan_status = plan.status

                # Find next step
                for step in plan.steps:
                    if step.status == "pending":
                        result.next_step = step.description
                        break

                # Update plan status based on outcome
                if outcome == "success" and result.steps_remaining == 0:
                    self.plan_mgr.complete(memory.current_plan_id)
                    result.plan_status = "completed"
                elif outcome == "abandoned":
                    self.plan_mgr.abandon(memory.current_plan_id, summary)
                    result.plan_status = "abandoned"

        # Count discoveries from this session
        result.discoveries_added = len([
            d for d in memory.discoveries
            if d.created_at and d.created_at.startswith(datetime.utcnow().strftime("%Y-%m-%d"))
        ])

        # End session and condense memory
        self.memory_mgr.end_session(summary)

        return result

    def activate_plan(self, plan_id: str) -> Optional[Plan]:
        """Activate a plan and update memory.

        Args:
            plan_id: Plan to activate

        Returns:
            The activated Plan, or None if not found
        """
        if self.plan_mgr.activate(plan_id):
            plan = self.plan_mgr.get(plan_id)
            if plan:
                self.memory_mgr.set_current_work(
                    ticket_id=plan.ticket_id,
                    plan_id=plan_id,
                    plan_title=plan.title,
                    plan_status="active",
                )

                # Update progress in memory
                progress = get_progress_summary(plan)
                current_step = None
                for step in plan.steps:
                    if step.status in ("in_progress", "pending"):
                        current_step = step.description
                        break

                self.memory_mgr.update_progress(
                    current_step=current_step,
                    completed_steps=progress["steps"]["completed"],
                    total_steps=progress["steps"]["total"],
                    blockers=progress["blockers"],
                )

                return plan
        return None

    def create_and_activate_plan(
        self,
        title: str,
        ticket_id: Optional[str] = None,
        steps: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
        tools: Optional[list[str]] = None,
        files: Optional[list[str]] = None,
    ) -> tuple[str, Plan]:
        """Create a new plan and activate it.

        Args:
            title: Plan title
            ticket_id: Optional ticket to link
            steps: Optional step descriptions
            acceptance_criteria: Optional AC text
            tools: Optional tool names
            files: Optional file paths

        Returns:
            Tuple of (plan_id, Plan)
        """
        plan_id = self.plan_mgr.create(
            title=title,
            ticket_id=ticket_id,
            steps=steps,
            acceptance_criteria=acceptance_criteria,
            tools=tools,
            files=files,
        )

        plan = self.activate_plan(plan_id)
        return plan_id, plan

    def record_step_complete(self, step_index: int, output: Optional[str] = None) -> None:
        """Record that a step was completed.

        Updates both the plan and memory.

        Args:
            step_index: Step index (1-based)
            output: Optional output from the step
        """
        memory = self.memory_mgr.get()
        if not memory.current_plan_id:
            return

        # Get step ID from plan
        steps = self.plan_mgr.get_steps(memory.current_plan_id)
        for step in steps:
            if step.order_index == step_index:
                self.plan_mgr.complete_step(step.id, output)
                break

        # Update memory
        plan = self.plan_mgr.get(memory.current_plan_id)
        if plan:
            progress = get_progress_summary(plan)

            # Find next step
            next_step = None
            for step in plan.steps:
                if step.status == "pending":
                    next_step = step.description
                    break

            self.memory_mgr.update_progress(
                current_step=next_step,
                completed_steps=progress["steps"]["completed"],
                total_steps=progress["steps"]["total"],
            )

    def record_deviation(self, step_index: int, reason: str, approved: bool = False) -> None:
        """Record a deviation from the plan.

        Args:
            step_index: Step that deviated
            reason: Why the deviation occurred
            approved: Whether user approved the deviation
        """
        memory = self.memory_mgr.get()
        if not memory.current_plan_id:
            return

        # Get step ID
        steps = self.plan_mgr.get_steps(memory.current_plan_id)
        for step in steps:
            if step.order_index == step_index:
                self.plan_mgr.skip_step(step.id, reason, approved)
                break

        # Add deviation as discovery
        self.memory_mgr.add_discovery(
            f"Deviation at step {step_index}: {reason}",
            importance=4,  # Deviations are high importance
            tags=["deviation"],
        )

    def add_discovery(self, content: str, importance: int = 2) -> None:
        """Add a discovery to memory.

        Args:
            content: What was discovered
            importance: 1-5, higher = more important
        """
        self.memory_mgr.add_discovery(content, importance)

    def add_blocker(self, blocker: str, step_index: Optional[int] = None) -> None:
        """Add a blocker.

        Args:
            blocker: Blocker description
            step_index: Optional step that is blocked
        """
        self.memory_mgr.add_blocker(blocker)

        # Also add to plan step if specified
        if step_index:
            memory = self.memory_mgr.get()
            if memory.current_plan_id:
                plan = self.plan_mgr.get(memory.current_plan_id)
                if plan:
                    from .toon import add_blocker as toon_add_blocker
                    toon_add_blocker(plan, step_index, blocker)
                    self.plan_mgr.update_content(memory.current_plan_id, plan)

    def resolve_blocker(self, blocker: str) -> None:
        """Mark a blocker as resolved.

        Args:
            blocker: Blocker to resolve
        """
        self.memory_mgr.remove_blocker(blocker)

    def get_status(self) -> dict:
        """Get current session status.

        Returns:
            Dict with status information
        """
        memory = self.memory_mgr.get()
        status = {
            "has_memory": memory.current_plan_id is not None or bool(memory.discoveries),
            "current_ticket": memory.current_ticket_id,
            "current_ticket_title": memory.current_ticket_title,
            "current_plan": memory.current_plan_id,
            "current_plan_title": memory.current_plan_title,
            "current_plan_status": memory.current_plan_status,
            "progress": {
                "current_step": memory.current_step,
                "completed": memory.completed_steps,
                "total": memory.total_steps,
            },
            "blockers": memory.blockers,
            "discoveries_count": len(memory.discoveries),
            "last_session": memory.last_session_end,
        }

        # Add active plan info if available
        active = self.plan_mgr.get_active()
        if active:
            plan_id, plan = active
            progress = get_progress_summary(plan)
            status["active_plan"] = {
                "id": plan_id,
                "title": plan.title,
                "status": plan.status,
                "progress": progress,
            }

        return status

    def suggest_next_work(self) -> dict:
        """Suggest what to work on next based on priorities and blockers.

        Analyzes all active/paused plans and returns recommendations
        sorted by priority, with blocked items separated.

        Returns:
            Dict with:
              - blocked: List of WorkSuggestion for blocked plans
              - ready: List of WorkSuggestion for unblocked plans (priority sorted)
              - recommended: The single best WorkSuggestion, or None
              - summary: Human-readable summary string
        """
        # Get all in-progress plans
        active_plans = self.plan_mgr.list(status="active")
        paused_plans = self.plan_mgr.list(status="paused")
        all_plans = active_plans + paused_plans

        blocked: list[WorkSuggestion] = []
        ready: list[WorkSuggestion] = []

        for plan_summary in all_plans:
            # Get full plan to check for blockers
            plan = self.plan_mgr.get(plan_summary.id)
            if not plan:
                continue

            progress = get_progress_summary(plan)
            has_blocker = bool(progress["blockers"])

            # Get ticket info for priority
            ticket_title = None
            priority = 2  # Default medium priority
            if plan_summary.ticket_id:
                ticket = self.ticket_mgr.get(plan_summary.ticket_id)
                if ticket:
                    ticket_title = ticket.title
                    priority = ticket.priority

            progress_str = f"{progress['steps']['completed']}/{progress['steps']['total']} steps"

            suggestion = WorkSuggestion(
                plan_id=plan_summary.id,
                plan_title=plan_summary.title,
                ticket_id=plan_summary.ticket_id,
                ticket_title=ticket_title,
                priority=priority,
                progress=progress_str,
                status=plan_summary.status,
                reason="",  # Will be set below
            )

            if has_blocker:
                suggestion.reason = f"Blocked: {progress['blockers'][0]}"
                blocked.append(suggestion)
            else:
                # Determine reason based on state
                if plan_summary.status == "active":
                    suggestion.reason = "Currently active"
                elif progress["steps"]["completed"] > 0:
                    suggestion.reason = f"{int(progress['steps']['completed'] / progress['steps']['total'] * 100)}% complete"
                else:
                    suggestion.reason = "Ready to start"
                ready.append(suggestion)

        # Sort ready by priority (highest first), then by progress (most complete first)
        ready.sort(key=lambda s: (-s.priority, -int(s.progress.split("/")[0])))

        # Determine recommended
        recommended = ready[0] if ready else None
        if recommended:
            recommended.reason = f"Highest priority ({recommended.priority}/4), {recommended.reason.lower()}"

        # Build summary
        summary_parts = []
        if blocked:
            summary_parts.append(f"{len(blocked)} blocked")
        if ready:
            summary_parts.append(f"{len(ready)} ready")
        if recommended:
            summary_parts.append(f"Recommended: {recommended.plan_title}")

        return {
            "blocked": blocked,
            "ready": ready,
            "recommended": recommended,
            "summary": " | ".join(summary_parts) if summary_parts else "No active work",
        }

    def quick_fix_note(self, description: str, importance: int = 2) -> None:
        """Record a quick fix without creating a plan.

        Use this for small fixes that don't warrant full plan tracking.
        The fix is noted in memory for context.

        Args:
            description: What was fixed
            importance: 1-5, default 2 (normal)
        """
        self.memory_mgr.add_discovery(
            f"Quick fix: {description}",
            importance=importance,
            tags=["quick-fix"],
        )
