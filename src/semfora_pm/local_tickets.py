"""Local ticket management for offline-first workflow.

Deprecated: This module now wraps TicketManager with source='local' to preserve
backwards compatibility while the app transitions to a single tickets table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from .db import Database
from .tickets import TicketManager, Ticket


TicketStatus = Literal["pending", "in_progress", "completed", "blocked", "canceled", "orphaned"]


def _status_category(status: str) -> str:
    status_map = {
        "pending": "todo",
        "in_progress": "in_progress",
        "completed": "done",
        "done": "done",
        "blocked": "in_progress",
        "canceled": "canceled",
        "orphaned": "canceled",
    }
    return status_map.get(status, "todo")


@dataclass
class LocalTicket:
    """A local ticket item."""

    id: str
    project_id: str
    title: str
    description: Optional[str] = None
    parent_ticket_id: Optional[str] = None  # Link to parent ticket (external_items UUID)
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
    """Manages local tickets for a project (compatibility wrapper)."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager."""
        self.db = db
        self.project_id = project_id
        self.ticket_mgr = TicketManager(db, project_id)

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        parent_ticket_id: Optional[str] = None,
        priority: int = 2,
        tags: Optional[list[str]] = None,
        status: TicketStatus = "pending",
    ) -> LocalTicket:
        """Create a new local ticket."""
        ticket_id = self.ticket_mgr.create(
            title=title,
            description=description,
            source="local",
            status=status,
            status_category=_status_category(status),
            priority=priority,
            tags=tags,
            parent_external_item_id=parent_ticket_id,
        )
        ticket = self.ticket_mgr.get(ticket_id)
        return _to_local_ticket(ticket)

    def get(self, ticket_id: str) -> Optional[LocalTicket]:
        """Get a ticket by ID."""
        ticket = self.ticket_mgr.get(ticket_id)
        if not ticket or ticket.source != "local":
            return None
        return _to_local_ticket(ticket)

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
        """Update a ticket."""
        status_category = _status_category(status) if status is not None else None
        ticket = self.ticket_mgr.update(
            ticket_id=ticket_id,
            title=title,
            description=description,
            status=status,
            status_category=status_category,
            priority=priority,
            tags=tags,
            parent_external_item_id=parent_ticket_id,
        )
        if not ticket or ticket.source != "local":
            return None
        return _to_local_ticket(ticket)

    def list(
        self,
        parent_ticket_id: Optional[str] = None,
        epic_id: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[list[str]] = None,
        include_completed: bool = False,
    ) -> list[LocalTicket]:
        """List tickets with filtering."""
        tickets = self.ticket_mgr.list_local(
            parent_external_item_id=parent_ticket_id,
            epic_id=epic_id,
            status=status,
            tags=tags,
            include_completed=include_completed,
        )
        return [_to_local_ticket(t) for t in tickets]

    def list_by_epic(self, epic_id: str, include_completed: bool = False) -> list[LocalTicket]:
        """Get all tickets linked to parent tickets in an epic."""
        return self.list(epic_id=epic_id, include_completed=include_completed)

    def delete(self, ticket_id: str) -> bool:
        """Delete a ticket and its dependencies."""
        return self.ticket_mgr.delete(ticket_id)

    def mark_orphaned(self, parent_ticket_id: str) -> int:
        """Mark all tickets linked to a parent ticket as orphaned."""
        with self.db.transaction() as conn:
            result = conn.execute(
                """
                UPDATE tickets
                SET status = 'orphaned',
                    status_category = 'canceled',
                    updated_at = ?
                WHERE project_id = ?
                  AND source = 'local'
                  AND parent_external_item_id = ?
                  AND status != 'orphaned'
                """,
                (datetime.utcnow().isoformat(), self.project_id, parent_ticket_id),
            )
            return result.rowcount

    def reorder(self, ticket_ids: list[str]) -> None:
        """Reorder tickets by setting their order_index."""
        with self.db.transaction() as conn:
            for index, ticket_id in enumerate(ticket_ids):
                conn.execute(
                    """
                    UPDATE tickets
                    SET order_index = ?, updated_at = ?
                    WHERE id = ? AND project_id = ? AND source = 'local'
                    """,
                    (index, datetime.utcnow().isoformat(), ticket_id, self.project_id),
                )


def _to_local_ticket(ticket: Ticket) -> LocalTicket:
    """Convert a Ticket to a LocalTicket."""
    return LocalTicket(
        id=ticket.id,
        project_id=ticket.project_id,
        title=ticket.title,
        description=ticket.description,
        parent_ticket_id=ticket.parent_external_item_id,
        status=ticket.status,
        priority=ticket.priority,
        order_index=ticket.order_index or 0,
        tags=list(ticket.tags or []),
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        completed_at=ticket.completed_at,
        linked_ticket_id=ticket.parent_external_id,
        linked_ticket_title=ticket.parent_external_title,
        linked_epic_id=ticket.parent_external_epic_id,
        linked_epic_name=ticket.parent_external_epic_name,
    )


# Backwards compatibility aliases (deprecated)
LocalPlan = LocalTicket
PlanManager = LocalTicketManager
PlanStatus = TicketStatus
