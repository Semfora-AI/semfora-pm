"""Local ticket management for offline-first workflow.

Local tickets are created locally and can optionally sync to Linear.
They support full offline operation with sync when connected.

Ticket sources:
- 'local': Created locally, not yet synced
- 'linear': Pulled from Linear
- 'synced': Created locally, successfully pushed to Linear
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from .db import Database


TicketStatus = Literal["pending", "in_progress", "completed", "blocked", "canceled", "orphaned"]


@dataclass
class LocalTicket:
    """A local ticket item."""

    id: str
    project_id: str
    title: str
    description: Optional[str] = None
    parent_ticket_id: Optional[str] = None  # Link to parent ticket (internal UUID)
    status: TicketStatus = "pending"
    priority: int = 2  # 0-4, higher = more important
    order_index: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None

    # Denormalized fields (populated from external_items when fetched)
    linked_ticket_id: Optional[str] = None  # Provider ID (e.g., "SEM-123")
    linked_ticket_title: Optional[str] = None
    linked_epic_id: Optional[str] = None
    linked_epic_name: Optional[str] = None


class LocalTicketManager:
    """Manages local tickets for a project."""

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
        description: Optional[str] = None,
        parent_ticket_id: Optional[str] = None,
        priority: int = 2,
        tags: Optional[list[str]] = None,
        status: TicketStatus = "pending",
    ) -> LocalTicket:
        """Create a new local ticket.

        Args:
            title: Ticket title
            description: Optional description
            parent_ticket_id: Internal UUID of parent ticket to link (optional)
            priority: 0-4, higher = more important (default 2)
            tags: Optional list of tags
            status: Initial status (default 'pending')

        Returns:
            The created LocalTicket
        """
        ticket_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        tags_json = json.dumps(tags or [])

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO local_tickets (
                    id, project_id, parent_ticket_id, title, description,
                    priority, tags, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id, self.project_id, parent_ticket_id, title,
                    description, priority, tags_json, status, now, now,
                ),
            )

        return self.get(ticket_id)

    def get(self, ticket_id: str) -> Optional[LocalTicket]:
        """Get a ticket by ID with denormalized parent ticket info.

        Args:
            ticket_id: Ticket UUID

        Returns:
            LocalTicket if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT t.*, e.provider_id, e.title as ext_title,
                       e.epic_id, e.epic_name
                FROM local_tickets t
                LEFT JOIN external_items e ON t.parent_ticket_id = e.id
                WHERE t.id = ?
                """,
                (ticket_id,),
            ).fetchone()

            if row:
                return self._row_to_ticket(row)
        return None

    def update(
        self,
        ticket_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[TicketStatus] = None,
        priority: Optional[int] = None,
        tags: Optional[list[str]] = None,
        parent_ticket_id: Optional[str] = None,
    ) -> Optional[LocalTicket]:
        """Update a ticket.

        Args:
            ticket_id: Ticket UUID
            title: New title
            description: New description
            status: New status
            priority: New priority (0-4)
            tags: New tags list
            parent_ticket_id: New parent ticket link (internal UUID)

        Returns:
            Updated LocalTicket if found, None otherwise
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "completed":
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
            elif status != "completed":
                # Clear completed_at if moving away from completed
                updates.append("completed_at = NULL")

        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)

        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))

        if parent_ticket_id is not None:
            updates.append("parent_ticket_id = ?")
            params.append(parent_ticket_id if parent_ticket_id else None)

        if not updates:
            return self.get(ticket_id)

        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(ticket_id)

        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE local_tickets SET {', '.join(updates)} WHERE id = ?",
                params,
            )

        return self.get(ticket_id)

    def list(
        self,
        parent_ticket_id: Optional[str] = None,
        epic_id: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[list[str]] = None,
        include_completed: bool = False,
    ) -> list[LocalTicket]:
        """List tickets with filtering.

        Args:
            parent_ticket_id: Filter by linked parent ticket (internal UUID)
            epic_id: Filter by epic (across all tickets in that epic!)
            status: Filter by status
            tags: Filter by any of these tags
            include_completed: Include completed/canceled/orphaned (default False)

        Returns:
            List of tickets ordered by priority (desc), order_index, created_at
        """
        conditions = ["t.project_id = ?"]
        params = [self.project_id]

        if parent_ticket_id:
            conditions.append("t.parent_ticket_id = ?")
            params.append(parent_ticket_id)

        if epic_id:
            conditions.append("e.epic_id = ?")
            params.append(epic_id)

        if status:
            conditions.append("t.status = ?")
            params.append(status)

        if not include_completed:
            conditions.append("t.status NOT IN ('completed', 'canceled', 'orphaned')")

        # Note: tag filtering is basic (any match). For complex queries, consider FTS.
        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("t.tags LIKE ?")
                params.append(f'%"{tag}"%')
            if tag_conditions:
                conditions.append(f"({' OR '.join(tag_conditions)})")

        where_clause = " AND ".join(conditions)

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*, e.provider_id, e.title as ext_title,
                       e.epic_id, e.epic_name
                FROM local_tickets t
                LEFT JOIN external_items e ON t.parent_ticket_id = e.id
                WHERE {where_clause}
                ORDER BY t.priority DESC, t.order_index ASC, t.created_at ASC
                """,
                params,
            ).fetchall()

            return [self._row_to_ticket(row) for row in rows]

    def list_by_epic(self, epic_id: str, include_completed: bool = False) -> list[LocalTicket]:
        """Get all tickets linked to parent tickets in an epic.

        This is a convenience method for grouping work across related tickets.

        Args:
            epic_id: Epic's provider ID
            include_completed: Include completed/canceled tickets

        Returns:
            List of tickets across all parent tickets in the epic
        """
        return self.list(epic_id=epic_id, include_completed=include_completed)

    def delete(self, ticket_id: str) -> bool:
        """Delete a ticket and its dependencies.

        Args:
            ticket_id: Ticket UUID

        Returns:
            True if deleted, False if not found
        """
        with self.db.transaction() as conn:
            # Delete dependencies involving this ticket
            conn.execute(
                """
                DELETE FROM dependencies
                WHERE (source_type = 'local' AND source_id = ?)
                   OR (target_type = 'local' AND target_id = ?)
                """,
                (ticket_id, ticket_id),
            )

            # Delete the ticket
            result = conn.execute(
                "DELETE FROM local_tickets WHERE id = ?",
                (ticket_id,),
            )
            return result.rowcount > 0

    def mark_orphaned(self, parent_ticket_id: str) -> int:
        """Mark all tickets linked to a parent ticket as orphaned.

        Called when a linked parent ticket is deleted from the provider.

        Args:
            parent_ticket_id: Internal UUID of the deleted parent ticket

        Returns:
            Number of tickets marked as orphaned
        """
        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE local_tickets
                SET status = 'orphaned', updated_at = ?
                WHERE parent_ticket_id = ? AND status != 'orphaned'
                """,
                (datetime.utcnow().isoformat(), parent_ticket_id),
            )
            return result.rowcount

    def reorder(self, ticket_ids: list[str]) -> None:
        """Reorder tickets by setting their order_index.

        Args:
            ticket_ids: List of ticket IDs in desired order
        """
        with self.db.transaction() as conn:
            for index, ticket_id in enumerate(ticket_ids):
                conn.execute(
                    "UPDATE local_tickets SET order_index = ? WHERE id = ?",
                    (index, ticket_id),
                )

    def _row_to_ticket(self, row) -> LocalTicket:
        """Convert a database row to a LocalTicket with denormalized data."""
        tags = json.loads(row["tags"]) if row["tags"] else []

        return LocalTicket(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            parent_ticket_id=row["parent_ticket_id"],
            status=row["status"],
            priority=row["priority"],
            order_index=row["order_index"],
            tags=tags,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            # Denormalized from external_items (parent ticket)
            linked_ticket_id=row["provider_id"] if "provider_id" in row.keys() else None,
            linked_ticket_title=row["ext_title"] if "ext_title" in row.keys() else None,
            linked_epic_id=row["epic_id"] if "epic_id" in row.keys() else None,
            linked_epic_name=row["epic_name"] if "epic_name" in row.keys() else None,
        )


# Backwards compatibility aliases (deprecated)
LocalPlan = LocalTicket
PlanManager = LocalTicketManager
PlanStatus = TicketStatus
