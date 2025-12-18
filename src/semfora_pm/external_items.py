"""External items manager - caching provider tickets for local linking.

This module handles caching ticket information from providers (like Linear)
so that local plans can link to them without constant API calls.

Cached items include epic context for grouping related work across tickets.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from .db import Database


StatusCategory = Literal["todo", "in_progress", "done", "canceled"]


@dataclass
class ExternalItem:
    """A cached external item (ticket, epic, etc.) from a provider."""

    id: str
    project_id: str
    provider_id: str  # e.g., "SEM-123"
    item_type: str  # 'ticket', 'epic', 'subtask'
    title: str
    description: Optional[str] = None
    status: Optional[str] = None  # Provider's raw status
    status_category: Optional[StatusCategory] = None  # Normalized
    priority: Optional[int] = None  # 0-4
    assignee: Optional[str] = None
    assignee_name: Optional[str] = None
    labels: list[str] = None
    epic_id: Optional[str] = None  # For grouping
    epic_name: Optional[str] = None
    sprint_id: Optional[str] = None
    sprint_name: Optional[str] = None
    url: Optional[str] = None
    provider_data: Optional[dict] = None
    created_at_provider: Optional[str] = None
    updated_at_provider: Optional[str] = None
    cached_at: Optional[str] = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = []


class ExternalItemsManager:
    """Manages cached external items from providers."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager.

        Args:
            db: Database connection
            project_id: Project ID for scoping queries
        """
        self.db = db
        self.project_id = project_id

    def cache_item(
        self,
        provider_id: str,
        title: str,
        item_type: str = "ticket",
        description: Optional[str] = None,
        status: Optional[str] = None,
        status_category: Optional[StatusCategory] = None,
        priority: Optional[int] = None,
        assignee: Optional[str] = None,
        assignee_name: Optional[str] = None,
        labels: Optional[list[str]] = None,
        epic_id: Optional[str] = None,
        epic_name: Optional[str] = None,
        sprint_id: Optional[str] = None,
        sprint_name: Optional[str] = None,
        url: Optional[str] = None,
        provider_data: Optional[dict] = None,
        created_at_provider: Optional[str] = None,
        updated_at_provider: Optional[str] = None,
    ) -> ExternalItem:
        """Cache an external item (insert or update).

        Args:
            provider_id: Provider's identifier (e.g., "SEM-123")
            title: Item title
            item_type: Type of item ('ticket', 'epic', 'subtask')
            ... other fields from the provider

        Returns:
            The cached ExternalItem
        """
        now = datetime.utcnow().isoformat()
        labels_json = json.dumps(labels or [])
        provider_data_json = json.dumps(provider_data) if provider_data else None

        with self.db.transaction() as conn:
            # Check if item already exists
            existing = conn.execute(
                "SELECT id FROM external_items WHERE project_id = ? AND provider_id = ?",
                (self.project_id, provider_id),
            ).fetchone()

            if existing:
                # Update existing item
                item_id = existing["id"]
                conn.execute(
                    """
                    UPDATE external_items SET
                        title = ?, description = ?, status = ?, status_category = ?,
                        priority = ?, assignee = ?, assignee_name = ?, labels = ?,
                        epic_id = ?, epic_name = ?, sprint_id = ?, sprint_name = ?,
                        url = ?, provider_data = ?, created_at_provider = ?,
                        updated_at_provider = ?, cached_at = ?
                    WHERE id = ?
                    """,
                    (
                        title, description, status, status_category, priority,
                        assignee, assignee_name, labels_json, epic_id, epic_name,
                        sprint_id, sprint_name, url, provider_data_json,
                        created_at_provider, updated_at_provider, now, item_id,
                    ),
                )
            else:
                # Insert new item
                item_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO external_items (
                        id, project_id, provider_id, item_type, title, description,
                        status, status_category, priority, assignee, assignee_name,
                        labels, epic_id, epic_name, sprint_id, sprint_name, url,
                        provider_data, created_at_provider, updated_at_provider, cached_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id, self.project_id, provider_id, item_type, title,
                        description, status, status_category, priority, assignee,
                        assignee_name, labels_json, epic_id, epic_name, sprint_id,
                        sprint_name, url, provider_data_json, created_at_provider,
                        updated_at_provider, now,
                    ),
                )

        return self.get_by_id(item_id)

    def get_by_id(self, item_id: str) -> Optional[ExternalItem]:
        """Get an external item by internal ID.

        Args:
            item_id: Internal UUID

        Returns:
            ExternalItem if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM external_items WHERE id = ?",
                (item_id,),
            ).fetchone()

            if row:
                return self._row_to_item(row)
        return None

    def get_by_provider_id(self, provider_id: str) -> Optional[ExternalItem]:
        """Get an external item by provider ID.

        Args:
            provider_id: Provider's identifier (e.g., "SEM-123")

        Returns:
            ExternalItem if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM external_items WHERE project_id = ? AND provider_id = ?",
                (self.project_id, provider_id),
            ).fetchone()

            if row:
                return self._row_to_item(row)
        return None

    def get_uuid_for_provider_id(self, provider_id: str) -> Optional[str]:
        """Get the internal UUID for a provider ID.

        Args:
            provider_id: Provider's identifier (e.g., "SEM-123")

        Returns:
            Internal UUID if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM external_items WHERE project_id = ? AND provider_id = ?",
                (self.project_id, provider_id),
            ).fetchone()

            return row["id"] if row else None

    def get_provider_id_for_uuid(self, item_id: str) -> Optional[str]:
        """Get the provider ID for an internal UUID.

        Args:
            item_id: Internal UUID

        Returns:
            Provider ID if found, None otherwise
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT provider_id FROM external_items WHERE id = ?",
                (item_id,),
            ).fetchone()

            return row["provider_id"] if row else None

    def list_by_epic(self, epic_id: str) -> list[ExternalItem]:
        """Get all items in an epic.

        Args:
            epic_id: Epic's provider ID

        Returns:
            List of items in the epic
        """
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM external_items WHERE project_id = ? AND epic_id = ?",
                (self.project_id, epic_id),
            ).fetchall()

            return [self._row_to_item(row) for row in rows]

    def is_stale(self, provider_id: str, max_age_seconds: int = 300) -> bool:
        """Check if a cached item is stale.

        Args:
            provider_id: Provider's identifier
            max_age_seconds: Maximum age in seconds (default 5 minutes)

        Returns:
            True if stale or not cached, False if fresh
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT cached_at FROM external_items WHERE project_id = ? AND provider_id = ?",
                (self.project_id, provider_id),
            ).fetchone()

            if not row or not row["cached_at"]:
                return True

            cached_at = datetime.fromisoformat(row["cached_at"])
            age = datetime.utcnow() - cached_at
            return age > timedelta(seconds=max_age_seconds)

    def delete(self, item_id: str) -> bool:
        """Delete a cached item.

        Args:
            item_id: Internal UUID

        Returns:
            True if deleted, False if not found
        """
        with self.db.transaction() as conn:
            result = conn.execute(
                "DELETE FROM external_items WHERE id = ?",
                (item_id,),
            )
            return result.rowcount > 0

    def _row_to_item(self, row) -> ExternalItem:
        """Convert a database row to an ExternalItem."""
        labels = json.loads(row["labels"]) if row["labels"] else []
        provider_data = json.loads(row["provider_data"]) if row["provider_data"] else None

        return ExternalItem(
            id=row["id"],
            project_id=row["project_id"],
            provider_id=row["provider_id"],
            item_type=row["item_type"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            status_category=row["status_category"],
            priority=row["priority"],
            assignee=row["assignee"],
            assignee_name=row["assignee_name"],
            labels=labels,
            epic_id=row["epic_id"],
            epic_name=row["epic_name"],
            sprint_id=row["sprint_id"],
            sprint_name=row["sprint_name"],
            url=row["url"],
            provider_data=provider_data,
            created_at_provider=row["created_at_provider"],
            updated_at_provider=row["updated_at_provider"],
            cached_at=row["cached_at"],
        )


def normalize_linear_status(status: str) -> StatusCategory:
    """Normalize Linear status to a category.

    Args:
        status: Linear status name

    Returns:
        Normalized status category
    """
    status_lower = status.lower()

    if status_lower in ("backlog", "triage", "todo", "unstarted"):
        return "todo"
    elif status_lower in ("in progress", "in_progress", "started"):
        return "in_progress"
    elif status_lower in ("done", "completed", "merged"):
        return "done"
    elif status_lower in ("canceled", "cancelled", "duplicate", "won't fix", "wontfix"):
        return "canceled"
    else:
        # Default to todo for unknown statuses
        return "todo"


def normalize_linear_priority(priority: Optional[int]) -> Optional[int]:
    """Normalize Linear priority (0-4 where 0=no priority, 1=urgent, 4=low).

    Linear uses: 0=none, 1=urgent, 2=high, 3=medium, 4=low
    We want: 0=none, 1=low, 2=medium, 3=high, 4=urgent

    Args:
        priority: Linear priority value

    Returns:
        Normalized priority (0-4, higher = more important)
    """
    if priority is None or priority == 0:
        return 0

    # Invert: 1->4, 2->3, 3->2, 4->1
    return 5 - priority
