"""Dependency graph management for local tickets and external items.

Supports blocking relationships and loose associations between items.
Works across both local tickets and cached external items.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from .db import Database


RelationType = Literal["blocks", "related_to"]
ItemType = Literal["external", "local"]


@dataclass
class Dependency:
    """A dependency relationship between items."""

    id: str
    source_type: ItemType
    source_id: str
    target_type: ItemType
    target_id: str
    relation: RelationType
    notes: Optional[str]
    created_at: str


@dataclass
class BlockerInfo:
    """Information about a blocking item."""

    item_type: ItemType
    item_id: str
    title: str
    status: str
    depth: int  # 1 = direct, 2+ = transitive
    resolved: bool


@dataclass
class ReadyWorkItem:
    """An item that is ready to work on (no unresolved blockers)."""

    item_type: ItemType
    item_id: str
    title: str
    status: str
    priority: int
    linked_ticket_id: Optional[str] = None  # For local tickets
    linked_epic_id: Optional[str] = None


class DependencyManager:
    """Manages dependencies between items."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager.

        Args:
            db: Database connection
            project_id: Project ID for scoping queries
        """
        self.db = db
        self.project_id = project_id

    def add(
        self,
        source_id: str,
        target_id: str,
        relation: RelationType,
        source_type: ItemType = "local",
        target_type: ItemType = "local",
        notes: Optional[str] = None,
    ) -> Dependency:
        """Add a dependency relationship.

        For 'blocks' relation: source blocks target
        (target can't start until source is done)

        Args:
            source_id: ID of the source item
            target_id: ID of the target item
            relation: Relationship type ('blocks' or 'related_to')
            source_type: Type of source ('local' or 'external')
            target_type: Type of target ('local' or 'external')
            notes: Optional notes about the dependency

        Returns:
            The created Dependency
        """
        dep_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO dependencies (
                    id, source_type, source_id, target_type, target_id,
                    relation, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dep_id, source_type, source_id, target_type, target_id,
                    relation, notes, now,
                ),
            )

        return Dependency(
            id=dep_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation=relation,
            notes=notes,
            created_at=now,
        )

    def remove(
        self,
        source_id: str,
        target_id: str,
        relation: Optional[str] = None,
        source_type: ItemType = "local",
        target_type: ItemType = "local",
    ) -> int:
        """Remove dependency relationship(s).

        Args:
            source_id: ID of the source item
            target_id: ID of the target item
            relation: Specific relation to remove (or all if None)
            source_type: Type of source
            target_type: Type of target

        Returns:
            Number of dependencies removed
        """
        conditions = [
            "source_type = ?", "source_id = ?",
            "target_type = ?", "target_id = ?"
        ]
        params = [source_type, source_id, target_type, target_id]

        if relation:
            conditions.append("relation = ?")
            params.append(relation)

        with self.db.transaction() as conn:
            result = conn.execute(
                f"DELETE FROM dependencies WHERE {' AND '.join(conditions)}",
                params,
            )
            return result.rowcount

    def get_blockers(
        self,
        item_id: str,
        item_type: ItemType = "local",
        recursive: bool = False,
        include_resolved: bool = False,
    ) -> list[BlockerInfo]:
        """Get items blocking this one.

        Args:
            item_id: ID of the item to check
            item_type: Type of the item
            recursive: Walk the full dependency tree (up to depth 10)
            include_resolved: Include already resolved blockers

        Returns:
            List of blocking items with their status
        """
        blockers = []
        visited = set()

        self._find_blockers(
            item_id, item_type, blockers, visited,
            depth=1, recursive=recursive, include_resolved=include_resolved,
        )

        return blockers

    def _find_blockers(
        self,
        item_id: str,
        item_type: ItemType,
        blockers: list[BlockerInfo],
        visited: set,
        depth: int,
        recursive: bool,
        include_resolved: bool,
    ) -> None:
        """Recursively find blockers."""
        if depth > 10:  # Prevent infinite loops
            return

        key = f"{item_type}:{item_id}"
        if key in visited:
            return
        visited.add(key)

        with self.db.connection() as conn:
            # Find items that block this one (source blocks target)
            rows = conn.execute(
                """
                SELECT source_type, source_id
                FROM dependencies
                WHERE target_type = ? AND target_id = ? AND relation = 'blocks'
                """,
                (item_type, item_id),
            ).fetchall()

            for row in rows:
                src_type = row["source_type"]
                src_id = row["source_id"]

                # Get item details
                info = self._get_item_info(conn, src_type, src_id)
                if info:
                    resolved = self._is_resolved(info["status"])

                    if include_resolved or not resolved:
                        blockers.append(BlockerInfo(
                            item_type=src_type,
                            item_id=src_id,
                            title=info["title"],
                            status=info["status"],
                            depth=depth,
                            resolved=resolved,
                        ))

                    if recursive:
                        self._find_blockers(
                            src_id, src_type, blockers, visited,
                            depth + 1, recursive, include_resolved,
                        )

    def get_dependents(
        self,
        item_id: str,
        item_type: ItemType = "local",
        recursive: bool = False,
    ) -> list[BlockerInfo]:
        """Get items blocked BY this one (reverse lookup).

        Useful for understanding impact of changes.

        Args:
            item_id: ID of the item
            item_type: Type of the item
            recursive: Walk the full dependency tree

        Returns:
            List of dependent items
        """
        dependents = []
        visited = set()

        self._find_dependents(
            item_id, item_type, dependents, visited,
            depth=1, recursive=recursive,
        )

        return dependents

    def _find_dependents(
        self,
        item_id: str,
        item_type: ItemType,
        dependents: list[BlockerInfo],
        visited: set,
        depth: int,
        recursive: bool,
    ) -> None:
        """Recursively find dependents."""
        if depth > 10:
            return

        key = f"{item_type}:{item_id}"
        if key in visited:
            return
        visited.add(key)

        with self.db.connection() as conn:
            # Find items that this one blocks (source blocks target -> find targets)
            rows = conn.execute(
                """
                SELECT target_type, target_id
                FROM dependencies
                WHERE source_type = ? AND source_id = ? AND relation = 'blocks'
                """,
                (item_type, item_id),
            ).fetchall()

            for row in rows:
                tgt_type = row["target_type"]
                tgt_id = row["target_id"]

                info = self._get_item_info(conn, tgt_type, tgt_id)
                if info:
                    dependents.append(BlockerInfo(
                        item_type=tgt_type,
                        item_id=tgt_id,
                        title=info["title"],
                        status=info["status"],
                        depth=depth,
                        resolved=self._is_resolved(info["status"]),
                    ))

                    if recursive:
                        self._find_dependents(
                            tgt_id, tgt_type, dependents, visited,
                            depth + 1, recursive,
                        )

    def get_ready_work(
        self,
        include_local: bool = True,
        limit: int = 5,
    ) -> list[ReadyWorkItem]:
        """Get unblocked items ready to work on.

        'Ready' means:
        - Status is 'pending' or 'in_progress' (for local) or 'todo'/'in_progress' (for external)
        - All blocking dependencies are resolved

        Args:
            include_local: Include local tickets
            limit: Maximum items to return

        Returns:
            List of ready work items ordered by priority
        """
        ready = []

        with self.db.connection() as conn:
            if include_local:
                # Get pending/in_progress local tickets
                rows = conn.execute(
                    """
                    SELECT t.id, t.title, t.status, t.priority,
                           e.provider_id as linked_ticket_id, e.epic_id
                    FROM local_tickets t
                    LEFT JOIN external_items e ON t.parent_ticket_id = e.id
                    WHERE t.project_id = ? AND t.status IN ('pending', 'in_progress')
                    ORDER BY t.priority DESC, t.created_at ASC
                    """,
                    (self.project_id,),
                ).fetchall()

                for row in rows:
                    # Check if this item has unresolved blockers
                    blockers = self.get_blockers(row["id"], "local", recursive=False)
                    if not blockers:  # No unresolved blockers
                        ready.append(ReadyWorkItem(
                            item_type="local",
                            item_id=row["id"],
                            title=row["title"],
                            status=row["status"],
                            priority=row["priority"],
                            linked_ticket_id=row["linked_ticket_id"],
                            linked_epic_id=row["epic_id"],
                        ))

        # Sort by priority and return limited results
        ready.sort(key=lambda x: (-x.priority, x.title))
        return ready[:limit]

    def _get_item_info(self, conn, item_type: ItemType, item_id: str) -> Optional[dict]:
        """Get basic info about an item."""
        if item_type == "local":
            row = conn.execute(
                "SELECT title, status FROM local_tickets WHERE id = ?",
                (item_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT title, status FROM external_items WHERE id = ?",
                (item_id,),
            ).fetchone()

        if row:
            return {"title": row["title"], "status": row["status"]}
        return None

    def _is_resolved(self, status: str) -> bool:
        """Check if a status indicates the item is resolved (done/completed/canceled)."""
        resolved_statuses = {"completed", "done", "canceled", "cancelled", "merged"}
        return status.lower() in resolved_statuses

    def list_all(
        self,
        item_id: Optional[str] = None,
        item_type: Optional[ItemType] = None,
        relation: Optional[RelationType] = None,
    ) -> list[Dependency]:
        """List dependencies with optional filtering.

        Args:
            item_id: Filter to deps involving this item (as source or target)
            item_type: Filter by item type (requires item_id)
            relation: Filter by relation type

        Returns:
            List of dependencies
        """
        conditions = []
        params = []

        if item_id:
            if item_type:
                conditions.append(
                    "((source_type = ? AND source_id = ?) OR (target_type = ? AND target_id = ?))"
                )
                params.extend([item_type, item_id, item_type, item_id])
            else:
                conditions.append("(source_id = ? OR target_id = ?)")
                params.extend([item_id, item_id])

        if relation:
            conditions.append("relation = ?")
            params.append(relation)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM dependencies WHERE {where_clause}",
                params,
            ).fetchall()

            return [
                Dependency(
                    id=row["id"],
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    target_type=row["target_type"],
                    target_id=row["target_id"],
                    relation=row["relation"],
                    notes=row["notes"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]
