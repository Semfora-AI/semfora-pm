"""Unified ticket management.

Tickets represent WHAT needs to be done. They can be:
- Local: Created locally, not synced to any provider
- External: Linked to a provider (Linear, Jira, etc.) via external_items

This module provides a unified interface for both types.
"""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

from .db import Database


TicketSource = Literal["local", "linear", "jira"]
TicketStatus = Literal["pending", "in_progress", "done", "canceled"]


@dataclass
class AcceptanceCriterion:
    """An acceptance criterion for a ticket."""
    index: int
    text: str
    status: str = "pending"  # pending, in_progress, verified, failed
    evidence: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"index": self.index, "text": self.text, "status": self.status}
        if self.evidence:
            d["evidence"] = self.evidence
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AcceptanceCriterion":
        return cls(
            index=d.get("index", 0),
            text=d.get("text", ""),
            status=d.get("status", "pending"),
            evidence=d.get("evidence"),
        )


@dataclass
class Ticket:
    """A unified ticket (local or external source)."""
    id: str
    project_id: str
    title: str
    source: TicketSource = "local"
    external_item_id: Optional[str] = None  # FK to external_items if linked

    description: Optional[str] = None
    status: str = "pending"
    status_category: Optional[str] = None  # normalized: todo, in_progress, done, canceled
    priority: int = 2  # 0-4, higher = more important

    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    created_at: str = ""
    updated_at: str = ""

    # Denormalized from external_items when linked
    external_id: Optional[str] = None  # e.g., "SEM-123"
    external_url: Optional[str] = None


@dataclass
class TicketSummary:
    """Lightweight ticket info for listings."""
    id: str
    title: str
    source: TicketSource
    status: str
    status_category: Optional[str]
    priority: int
    external_id: Optional[str] = None
    has_ac: bool = False


class TicketManager:
    """Manages unified tickets."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager.

        Args:
            db: Database connection
            project_id: Project ID for scoping
        """
        self.db = db
        self.project_id = project_id

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        acceptance_criteria: Optional[list[str]] = None,
        source: TicketSource = "local",
        priority: int = 2,
        labels: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> str:
        """Create a new ticket.

        Args:
            title: Ticket title
            description: Optional description
            acceptance_criteria: Optional list of AC text
            source: Source type (local, linear, jira)
            priority: 0-4, higher = more important
            labels: Optional labels
            tags: Optional local tags

        Returns:
            Created ticket ID
        """
        ticket_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        # Build AC JSON
        ac_list = []
        if acceptance_criteria:
            for i, text in enumerate(acceptance_criteria):
                ac_list.append({"index": i, "text": text, "status": "pending"})

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    id, project_id, source, title, description,
                    status, status_category, priority,
                    acceptance_criteria, labels, tags,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    self.project_id,
                    source,
                    title,
                    description,
                    "pending",
                    "todo",
                    priority,
                    json.dumps(ac_list) if ac_list else None,
                    json.dumps(labels) if labels else None,
                    json.dumps(tags) if tags else None,
                    now,
                    now,
                ),
            )

        return ticket_id

    def get(self, ticket_id: str) -> Optional[Ticket]:
        """Get a ticket by ID.

        Args:
            ticket_id: Ticket UUID

        Returns:
            Ticket if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT t.*, e.provider_id, e.url as external_url
                FROM tickets t
                LEFT JOIN external_items e ON t.external_item_id = e.id
                WHERE t.id = ?
                """,
                (ticket_id,),
            ).fetchone()

            if row:
                return self._row_to_ticket(row)
        return None

    def get_by_external_id(self, external_id: str) -> Optional[Ticket]:
        """Get a ticket by external provider ID (e.g., "SEM-123").

        Args:
            external_id: Provider ID

        Returns:
            Ticket if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT t.*, e.provider_id, e.url as external_url
                FROM tickets t
                JOIN external_items e ON t.external_item_id = e.id
                WHERE e.provider_id = ? AND t.project_id = ?
                """,
                (external_id, self.project_id),
            ).fetchone()

            if row:
                return self._row_to_ticket(row)
        return None

    def list(
        self,
        source: Optional[TicketSource] = None,
        status: Optional[str] = None,
        status_category: Optional[str] = None,
        priority: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TicketSummary]:
        """List tickets with optional filtering.

        Args:
            source: Filter by source
            status: Filter by status
            status_category: Filter by normalized status
            priority: Filter by priority
            limit: Maximum results
            offset: Skip first N

        Returns:
            List of TicketSummary
        """
        conditions = ["t.project_id = ?"]
        params: list = [self.project_id]

        if source:
            conditions.append("t.source = ?")
            params.append(source)
        if status:
            conditions.append("t.status = ?")
            params.append(status)
        if status_category:
            conditions.append("t.status_category = ?")
            params.append(status_category)
        if priority is not None:
            conditions.append("t.priority = ?")
            params.append(priority)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT t.id, t.title, t.source, t.status, t.status_category,
                       t.priority, t.acceptance_criteria, e.provider_id
                FROM tickets t
                LEFT JOIN external_items e ON t.external_item_id = e.id
                WHERE {where_clause}
                ORDER BY t.priority DESC, t.created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()

            return [
                TicketSummary(
                    id=row["id"],
                    title=row["title"],
                    source=row["source"],
                    status=row["status"],
                    status_category=row["status_category"],
                    priority=row["priority"],
                    external_id=row["provider_id"],
                    has_ac=bool(row["acceptance_criteria"]),
                )
                for row in rows
            ]

    def update(
        self,
        ticket_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        status_category: Optional[str] = None,
        priority: Optional[int] = None,
        labels: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[Ticket]:
        """Update a ticket.

        Args:
            ticket_id: Ticket to update
            title: New title
            description: New description
            status: New status
            status_category: New normalized status
            priority: New priority
            labels: New labels
            tags: New tags

        Returns:
            Updated Ticket, or None if not found
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
        if status_category is not None:
            updates.append("status_category = ?")
            params.append(status_category)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if labels is not None:
            updates.append("labels = ?")
            params.append(json.dumps(labels))
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))

        if not updates:
            return self.get(ticket_id)

        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())
        params.append(ticket_id)
        params.append(self.project_id)

        with self.db.transaction() as conn:
            conn.execute(
                f"""
                UPDATE tickets SET {', '.join(updates)}
                WHERE id = ? AND project_id = ?
                """,
                params,
            )

        return self.get(ticket_id)

    def link_external(self, ticket_id: str, external_item_id: str) -> bool:
        """Link a ticket to an external item.

        Args:
            ticket_id: Ticket to link
            external_item_id: External item to link to

        Returns:
            True if linked successfully
        """
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            # Get source from external item
            ext_row = conn.execute(
                "SELECT provider_id FROM external_items WHERE id = ?",
                (external_item_id,),
            ).fetchone()

            if not ext_row:
                return False

            result = conn.execute(
                """
                UPDATE tickets
                SET external_item_id = ?, source = 'linear', updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (external_item_id, now, ticket_id, self.project_id),
            )
            return result.rowcount > 0

    def update_ac_status(
        self,
        ticket_id: str,
        ac_index: int,
        status: str,
        evidence: Optional[str] = None,
    ) -> bool:
        """Update an acceptance criterion's status.

        Args:
            ticket_id: Ticket containing the AC
            ac_index: AC index (0-based)
            status: New status (pending, in_progress, verified, failed)
            evidence: Optional evidence of completion

        Returns:
            True if updated
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT acceptance_criteria FROM tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()

            if not row or not row["acceptance_criteria"]:
                return False

            ac_list = json.loads(row["acceptance_criteria"])
            for ac in ac_list:
                if ac["index"] == ac_index:
                    ac["status"] = status
                    if evidence:
                        ac["evidence"] = evidence
                    break
            else:
                return False

            conn.execute(
                "UPDATE tickets SET acceptance_criteria = ?, updated_at = ? WHERE id = ?",
                (json.dumps(ac_list), datetime.utcnow().isoformat(), ticket_id),
            )
            return True

    def add_acceptance_criterion(self, ticket_id: str, text: str) -> int:
        """Add an acceptance criterion to a ticket.

        Args:
            ticket_id: Ticket to add to
            text: AC text

        Returns:
            Index of the new AC
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT acceptance_criteria FROM tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()

            ac_list = json.loads(row["acceptance_criteria"]) if row and row["acceptance_criteria"] else []
            new_index = len(ac_list)
            ac_list.append({"index": new_index, "text": text, "status": "pending"})

            conn.execute(
                "UPDATE tickets SET acceptance_criteria = ?, updated_at = ? WHERE id = ?",
                (json.dumps(ac_list), datetime.utcnow().isoformat(), ticket_id),
            )
            return new_index

    def delete(self, ticket_id: str) -> bool:
        """Delete a ticket.

        Args:
            ticket_id: Ticket to delete

        Returns:
            True if deleted
        """
        with self.db.transaction() as conn:
            result = conn.execute(
                "DELETE FROM tickets WHERE id = ? AND project_id = ?",
                (ticket_id, self.project_id),
            )
            return result.rowcount > 0

    def search(self, query: str, limit: int = 10) -> list[TicketSummary]:
        """Search tickets by title or description.

        Args:
            query: Search text
            limit: Maximum results

        Returns:
            Matching tickets
        """
        if not query:
            return []

        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.title, t.source, t.status, t.status_category,
                       t.priority, t.acceptance_criteria, e.provider_id
                FROM tickets t
                LEFT JOIN external_items e ON t.external_item_id = e.id
                WHERE t.project_id = ? AND (t.title LIKE ? OR t.description LIKE ?)
                ORDER BY t.priority DESC, t.created_at DESC
                LIMIT ?
                """,
                (self.project_id, f"%{query}%", f"%{query}%", limit),
            ).fetchall()

            return [
                TicketSummary(
                    id=row["id"],
                    title=row["title"],
                    source=row["source"],
                    status=row["status"],
                    status_category=row["status_category"],
                    priority=row["priority"],
                    external_id=row["provider_id"],
                    has_ac=bool(row["acceptance_criteria"]),
                )
                for row in rows
            ]

    def _row_to_ticket(self, row) -> Ticket:
        """Convert a database row to a Ticket."""
        ac_list = []
        if row["acceptance_criteria"]:
            for ac_dict in json.loads(row["acceptance_criteria"]):
                ac_list.append(AcceptanceCriterion.from_dict(ac_dict))

        labels = json.loads(row["labels"]) if row["labels"] else []
        tags = json.loads(row["tags"]) if row["tags"] else []

        # sqlite3.Row doesn't have .get(), so we need to handle optional columns
        row_dict = dict(row)

        return Ticket(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            source=row["source"],
            external_item_id=row["external_item_id"],
            description=row["description"],
            status=row["status"],
            status_category=row["status_category"],
            priority=row["priority"],
            acceptance_criteria=ac_list,
            labels=labels,
            tags=tags,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            external_id=row_dict.get("provider_id"),
            external_url=row_dict.get("external_url"),
        )
