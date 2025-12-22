"""Plan management for the Plans-as-Memory architecture.

Plans track HOW to accomplish a ticket - the implementation strategy,
steps, progress, blockers, and discoveries. They are the foundation
of agent memory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json

from .db import Database
from .toon import (
    Plan, PlanStep, AcceptanceCriterion, PlanNote,
    serialize, deserialize, create_plan, get_progress_summary,
)


PlanStatus = str  # draft, active, paused, completed, abandoned


@dataclass
class PlanSummary:
    """Lightweight plan info for listings."""
    id: str
    project_id: str
    ticket_id: Optional[str]
    title: str
    status: PlanStatus
    created_at: str
    updated_at: str
    step_count: int = 0
    completed_steps: int = 0


@dataclass
class PlanStepRecord:
    """Database record for a plan step."""
    id: str
    plan_id: str
    order_index: int
    description: str
    status: str
    deviated: bool
    deviation_reason: Optional[str]
    deviation_approved: Optional[bool]
    output: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]


class PlanManager:
    """Manages plans and plan steps in the database."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager.

        Args:
            db: Database connection
            project_id: Project ID for scoping queries
        """
        self.db = db
        self.project_id = project_id

    def create(
        self,
        title: str,
        ticket_id: Optional[str] = None,
        steps: Optional[list[str]] = None,
        acceptance_criteria: Optional[list[str]] = None,
        tools: Optional[list[str]] = None,
        files: Optional[list[str]] = None,
    ) -> str:
        """Create a new plan.

        Args:
            title: Plan title
            ticket_id: Optional ticket ID to link to
            steps: Optional list of step descriptions
            acceptance_criteria: Optional list of AC text
            tools: Optional list of tool names
            files: Optional list of file paths

        Returns:
            The created plan ID
        """
        plan_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Create the Plan object and serialize to TOON
        plan = create_plan(
            title=title,
            ticket_id=ticket_id,
            steps=steps,
            acceptance_criteria=acceptance_criteria,
            tools=tools,
            files=files,
        )
        toon_content = serialize(plan)

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO plans (
                    id, project_id, ticket_id, title, toon_content,
                    status, tools_referenced, files_referenced, ac_indices,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    self.project_id,
                    ticket_id,
                    title,
                    toon_content,
                    "draft",
                    json.dumps(tools or []),
                    json.dumps(files or []),
                    json.dumps(list(range(len(acceptance_criteria or [])))),
                    now,
                    now,
                ),
            )

            # Create step records for granular tracking
            if steps:
                for i, desc in enumerate(steps, start=1):
                    step_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO plan_steps (
                            id, plan_id, order_index, description, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (step_id, plan_id, i, desc, "pending", now),
                    )

        return plan_id

    def get(self, plan_id: str) -> Optional[Plan]:
        """Get a plan by ID with full content.

        Args:
            plan_id: Plan UUID

        Returns:
            Plan object if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()

            if row:
                plan = deserialize(row["toon_content"])
                # Sync status from DB column (source of truth)
                plan.status = row["status"]
                return plan
        return None

    def get_with_metadata(self, plan_id: str) -> Optional[tuple[Plan, dict]]:
        """Get a plan with database metadata.

        Args:
            plan_id: Plan UUID

        Returns:
            Tuple of (Plan, metadata dict) if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()

            if row:
                plan = deserialize(row["toon_content"])
                # Sync status from DB column (source of truth)
                plan.status = row["status"]
                metadata = {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "ticket_id": row["ticket_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "activated_at": row["activated_at"],
                    "completed_at": row["completed_at"],
                }
                return plan, metadata
        return None

    def list(
        self,
        ticket_id: Optional[str] = None,
        status: Optional[PlanStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[PlanSummary]:
        """List plans with optional filtering.

        Args:
            ticket_id: Filter by ticket
            status: Filter by status
            limit: Maximum results
            offset: Skip first N results

        Returns:
            List of PlanSummary objects
        """
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if ticket_id:
            conditions.append("ticket_id = ?")
            params.append(ticket_id)

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT p.*,
                       (SELECT COUNT(*) FROM plan_steps WHERE plan_id = p.id) as step_count,
                       (SELECT COUNT(*) FROM plan_steps WHERE plan_id = p.id AND status = 'completed') as completed_steps
                FROM plans p
                WHERE {where_clause}
                ORDER BY p.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()

            return [
                PlanSummary(
                    id=row["id"],
                    project_id=row["project_id"],
                    ticket_id=row["ticket_id"],
                    title=row["title"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    step_count=row["step_count"],
                    completed_steps=row["completed_steps"],
                )
                for row in rows
            ]

    def count(
        self,
        ticket_id: Optional[str] = None,
        status: Optional[PlanStatus] = None,
    ) -> int:
        """Count plans with optional filtering."""
        conditions = ["project_id = ?"]
        params: list = [self.project_id]

        if ticket_id:
            conditions.append("ticket_id = ?")
            params.append(ticket_id)

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions)

        with self.db.connection() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) as count
                FROM plans p
                WHERE {where_clause}
                """,
                params,
            ).fetchone()

        return int(row["count"]) if row else 0

    def search(self, query: str, limit: int = 10) -> list[PlanSummary]:
        """Search plans by title or content.

        Args:
            query: Search text
            limit: Maximum results

        Returns:
            Matching plans
        """
        if not query:
            return []

        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM plan_steps WHERE plan_id = p.id) as step_count,
                       (SELECT COUNT(*) FROM plan_steps WHERE plan_id = p.id AND status = 'completed') as completed_steps
                FROM plans p
                WHERE p.project_id = ? AND (p.title LIKE ? OR p.toon_content LIKE ?)
                ORDER BY p.updated_at DESC
                LIMIT ?
                """,
                (self.project_id, f"%{query}%", f"%{query}%", limit),
            ).fetchall()

            return [
                PlanSummary(
                    id=row["id"],
                    project_id=row["project_id"],
                    ticket_id=row["ticket_id"],
                    title=row["title"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    step_count=row["step_count"],
                    completed_steps=row["completed_steps"],
                )
                for row in rows
            ]

    def activate(self, plan_id: str) -> bool:
        """Activate a plan, pausing any other active plans.

        Args:
            plan_id: Plan to activate

        Returns:
            True if activated, False if not found
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            # Pause any currently active plans
            conn.execute(
                """
                UPDATE plans SET status = 'paused', updated_at = ?
                WHERE project_id = ? AND status = 'active'
                """,
                (now, self.project_id),
            )

            # Activate this plan
            result = conn.execute(
                """
                UPDATE plans SET status = 'active', activated_at = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (now, now, plan_id, self.project_id),
            )

            # Update toon_content status
            if result.rowcount > 0:
                row = conn.execute(
                    "SELECT toon_content FROM plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
                if row:
                    plan = deserialize(row["toon_content"])
                    plan.status = "active"
                    conn.execute(
                        "UPDATE plans SET toon_content = ? WHERE id = ?",
                        (serialize(plan), plan_id),
                    )

            return result.rowcount > 0

    def complete(self, plan_id: str) -> bool:
        """Mark a plan as completed.

        Args:
            plan_id: Plan to complete

        Returns:
            True if completed, False if not found
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plans SET status = 'completed', completed_at = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (now, now, plan_id, self.project_id),
            )

            if result.rowcount > 0:
                row = conn.execute(
                    "SELECT toon_content FROM plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
                if row:
                    plan = deserialize(row["toon_content"])
                    plan.status = "completed"
                    conn.execute(
                        "UPDATE plans SET toon_content = ? WHERE id = ?",
                        (serialize(plan), plan_id),
                    )

            return result.rowcount > 0

    def abandon(self, plan_id: str, reason: Optional[str] = None) -> bool:
        """Mark a plan as abandoned.

        Args:
            plan_id: Plan to abandon
            reason: Optional reason for abandonment

        Returns:
            True if abandoned, False if not found
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plans SET status = 'abandoned', updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (now, plan_id, self.project_id),
            )

            if result.rowcount > 0:
                row = conn.execute(
                    "SELECT toon_content FROM plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
                if row:
                    plan = deserialize(row["toon_content"])
                    plan.status = "abandoned"
                    if reason:
                        plan.notes.append(PlanNote(note_type="comment", content=f"Abandoned: {reason}"))
                    conn.execute(
                        "UPDATE plans SET toon_content = ? WHERE id = ?",
                        (serialize(plan), plan_id),
                    )

            return result.rowcount > 0

    def update_content(self, plan_id: str, plan: Plan) -> bool:
        """Update the plan's TOON content.

        Args:
            plan_id: Plan to update
            plan: Updated Plan object

        Returns:
            True if updated, False if not found
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plans SET toon_content = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (serialize(plan), now, plan_id, self.project_id),
            )
            return result.rowcount > 0

    def update(
        self,
        plan_id: str,
        ticket_id: Optional[str] = None,
        title: Optional[str] = None,
        tools: Optional[list[str]] = None,
        files: Optional[list[str]] = None,
    ) -> Optional[Plan]:
        """Update a plan's metadata.

        Use this to retroactively link a plan to a ticket, update title, etc.

        Args:
            plan_id: Plan to update
            ticket_id: New ticket ID to link (or empty string to unlink)
            title: New title
            tools: New tools list
            files: New files list

        Returns:
            Updated Plan, or None if not found
        """
        now = datetime.utcnow().isoformat()

        updates = []
        params: list = []

        if ticket_id is not None:
            updates.append("ticket_id = ?")
            params.append(ticket_id if ticket_id else None)

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if tools is not None:
            updates.append("tools_referenced = ?")
            params.append(json.dumps(tools))

        if files is not None:
            updates.append("files_referenced = ?")
            params.append(json.dumps(files))

        if not updates:
            return self.get(plan_id)

        updates.append("updated_at = ?")
        params.append(now)
        params.append(plan_id)
        params.append(self.project_id)

        with self.db.transaction() as conn:
            result = conn.execute(
                f"""
                UPDATE plans SET {', '.join(updates)}
                WHERE id = ? AND project_id = ?
                """,
                params,
            )

            if result.rowcount > 0:
                # Also update toon_content if title or ticket changed
                row = conn.execute(
                    "SELECT toon_content FROM plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
                if row:
                    plan = deserialize(row["toon_content"])
                    if title is not None:
                        plan.title = title
                    if ticket_id is not None:
                        plan.ticket_id = ticket_id if ticket_id else None
                    if tools is not None:
                        plan.tools = tools
                    if files is not None:
                        plan.files = files
                    conn.execute(
                        "UPDATE plans SET toon_content = ? WHERE id = ?",
                        (serialize(plan), plan_id),
                    )

        return self.get(plan_id)

    def get_active(self) -> Optional[tuple[str, Plan]]:
        """Get the currently active plan.

        Returns:
            Tuple of (plan_id, Plan) if there's an active plan, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT id, toon_content, status FROM plans
                WHERE project_id = ? AND status = 'active'
                LIMIT 1
                """,
                (self.project_id,),
            ).fetchone()

            if row:
                plan = deserialize(row["toon_content"])
                # Sync status from DB column (source of truth)
                plan.status = row["status"]
                return row["id"], plan
        return None

    # --- Step Management ---

    def get_steps(self, plan_id: str) -> list[PlanStepRecord]:
        """Get all steps for a plan.

        Args:
            plan_id: Plan UUID

        Returns:
            List of step records ordered by index
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM plan_steps
                WHERE plan_id = ?
                ORDER BY order_index ASC
                """,
                (plan_id,),
            ).fetchall()

            return [
                PlanStepRecord(
                    id=row["id"],
                    plan_id=row["plan_id"],
                    order_index=row["order_index"],
                    description=row["description"],
                    status=row["status"],
                    deviated=bool(row["deviated"]),
                    deviation_reason=row["deviation_reason"],
                    deviation_approved=bool(row["deviation_approved"]) if row["deviation_approved"] is not None else None,
                    output=row["output"],
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                )
                for row in rows
            ]

    def start_step(self, step_id: str) -> bool:
        """Mark a step as in progress.

        Args:
            step_id: Step UUID

        Returns:
            True if updated
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plan_steps SET status = 'in_progress', started_at = ?
                WHERE id = ?
                """,
                (now, step_id),
            )

            if result.rowcount > 0:
                # Also update the toon_content
                self._sync_step_to_toon(conn, step_id)

            return result.rowcount > 0

    def complete_step(self, step_id: str, output: Optional[str] = None) -> bool:
        """Mark a step as completed.

        Args:
            step_id: Step UUID
            output: Optional output/result from completing this step

        Returns:
            True if updated
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plan_steps SET status = 'completed', completed_at = ?, output = ?
                WHERE id = ?
                """,
                (now, output, step_id),
            )

            if result.rowcount > 0:
                self._sync_step_to_toon(conn, step_id)

            return result.rowcount > 0

    def skip_step(self, step_id: str, reason: str, approved: bool = False) -> bool:
        """Skip a step with deviation tracking.

        Args:
            step_id: Step UUID
            reason: Why the step is being skipped
            approved: Whether the deviation was approved by user

        Returns:
            True if updated
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE plan_steps
                SET status = 'skipped', deviated = 1, deviation_reason = ?,
                    deviation_approved = ?, completed_at = ?
                WHERE id = ?
                """,
                (reason, int(approved), now, step_id),
            )

            if result.rowcount > 0:
                self._sync_step_to_toon(conn, step_id)

            return result.rowcount > 0

    def add_step(self, plan_id: str, description: str, after_index: Optional[int] = None) -> str:
        """Add a new step to a plan.

        Args:
            plan_id: Plan to add step to
            description: Step description
            after_index: Insert after this index (appends if None)

        Returns:
            New step ID
        """
        step_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            if after_index is not None:
                # Shift existing steps
                conn.execute(
                    """
                    UPDATE plan_steps SET order_index = order_index + 1
                    WHERE plan_id = ? AND order_index > ?
                    """,
                    (plan_id, after_index),
                )
                new_index = after_index + 1
            else:
                # Get max index
                row = conn.execute(
                    "SELECT MAX(order_index) as max_idx FROM plan_steps WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
                new_index = (row["max_idx"] or 0) + 1

            conn.execute(
                """
                INSERT INTO plan_steps (id, plan_id, order_index, description, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (step_id, plan_id, new_index, description, now),
            )

            # Update toon_content
            row = conn.execute(
                "SELECT toon_content FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row:
                plan = deserialize(row["toon_content"])
                plan.steps.append(PlanStep(index=new_index, description=description))
                plan.steps.sort(key=lambda s: s.index)
                conn.execute(
                    "UPDATE plans SET toon_content = ?, updated_at = ? WHERE id = ?",
                    (serialize(plan), now, plan_id),
                )

        return step_id

    def _sync_step_to_toon(self, conn, step_id: str) -> None:
        """Sync a step's status to the plan's TOON content."""
        row = conn.execute(
            """
            SELECT ps.*, p.toon_content, p.id as plan_id
            FROM plan_steps ps
            JOIN plans p ON ps.plan_id = p.id
            WHERE ps.id = ?
            """,
            (step_id,),
        ).fetchone()

        if row:
            plan = deserialize(row["toon_content"])
            for step in plan.steps:
                if step.index == row["order_index"]:
                    step.status = row["status"]
                    step.output = row["output"]
                    step.deviated = bool(row["deviated"])
                    step.deviation_reason = row["deviation_reason"]
                    break

            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE plans SET toon_content = ?, updated_at = ? WHERE id = ?",
                (serialize(plan), now, row["plan_id"]),
            )

    def delete(self, plan_id: str) -> bool:
        """Delete a plan and its steps.

        Args:
            plan_id: Plan to delete

        Returns:
            True if deleted
        """
        with self.db.transaction() as conn:
            # Steps are deleted by CASCADE
            result = conn.execute(
                "DELETE FROM plans WHERE id = ? AND project_id = ?",
                (plan_id, self.project_id),
            )
            return result.rowcount > 0
