"""Memory management for session continuity.

Memory is condensed per-project context that enables agents to resume work
across sessions without losing important discoveries, blockers, and progress.

Token budget: ~4000 tokens max
- Active Work: 40% - Current ticket + plan status
- Progress: 25% - Steps completed, blockers
- Discoveries: 20% - Patterns learned, decisions made
- Reference: 15% - Key files, commands, tools
"""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from .db import Database

try:
    from toon_format import encode, decode
except ImportError:
    def encode(obj: Any) -> str:
        return json.dumps(obj, indent=2)
    def decode(s: str) -> Any:
        return json.loads(s)


# Approximate token counts for budget management
TOKENS_PER_CHAR = 0.25  # Rough estimate: 4 chars per token
MAX_MEMORY_TOKENS = 4000
MAX_MEMORY_CHARS = int(MAX_MEMORY_TOKENS / TOKENS_PER_CHAR)


@dataclass
class Discovery:
    """A key discovery or learning."""
    content: str
    importance: int = 2  # 1-5, higher = more important
    created_at: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ProjectMemory:
    """Condensed project context for session continuity."""
    # Current state
    current_ticket_id: Optional[str] = None
    current_ticket_title: Optional[str] = None
    current_plan_id: Optional[str] = None
    current_plan_title: Optional[str] = None
    current_plan_status: Optional[str] = None

    # Progress summary
    current_step: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    blockers: list[str] = field(default_factory=list)

    # Discoveries and decisions
    discoveries: list[Discovery] = field(default_factory=list)

    # Reference
    key_files: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)

    # Metadata
    last_session_end: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for TOON serialization."""
        d = {}

        # Current work (most important)
        if self.current_ticket_id:
            d["ticket"] = {
                "id": self.current_ticket_id,
                "title": self.current_ticket_title,
            }
        if self.current_plan_id:
            d["plan"] = {
                "id": self.current_plan_id,
                "title": self.current_plan_title,
                "status": self.current_plan_status,
            }

        # Progress
        if self.current_step or self.total_steps > 0:
            d["progress"] = {
                "current": self.current_step,
                "done": self.completed_steps,
                "total": self.total_steps,
            }

        if self.blockers:
            d["blockers"] = self.blockers

        # Discoveries (compact)
        if self.discoveries:
            d["discoveries"] = [
                {"c": disc.content, "i": disc.importance}
                for disc in self.discoveries
            ]

        # Reference
        if self.key_files:
            d["files"] = self.key_files
        if self.available_tools:
            d["tools"] = self.available_tools

        # Metadata
        if self.last_session_end:
            d["last_session"] = self.last_session_end

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectMemory":
        """Create from dict (after TOON decode)."""
        ticket = d.get("ticket", {})
        plan = d.get("plan", {})
        progress = d.get("progress", {})

        discoveries = []
        for disc in d.get("discoveries", []):
            discoveries.append(Discovery(
                content=disc.get("c", disc.get("content", "")),
                importance=disc.get("i", disc.get("importance", 2)),
            ))

        return cls(
            current_ticket_id=ticket.get("id"),
            current_ticket_title=ticket.get("title"),
            current_plan_id=plan.get("id"),
            current_plan_title=plan.get("title"),
            current_plan_status=plan.get("status"),
            current_step=progress.get("current"),
            completed_steps=progress.get("done", 0),
            total_steps=progress.get("total", 0),
            blockers=d.get("blockers", []),
            discoveries=discoveries,
            key_files=d.get("files", []),
            available_tools=d.get("tools", []),
            last_session_end=d.get("last_session"),
        )

    def estimate_tokens(self) -> int:
        """Estimate the token count of this memory."""
        serialized = encode(self.to_dict())
        return int(len(serialized) * TOKENS_PER_CHAR)


class MemoryManager:
    """Manages project memory for session continuity."""

    def __init__(self, db: Database, project_id: str):
        """Initialize the manager.

        Args:
            db: Database connection
            project_id: Project ID
        """
        self.db = db
        self.project_id = project_id

    def get(self) -> ProjectMemory:
        """Get the current project memory.

        Returns:
            ProjectMemory object (empty if none exists)
        """
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM project_memory WHERE project_id = ?
                """,
                (self.project_id,),
            ).fetchone()

            if row and row["memory_blob"]:
                try:
                    data = decode(row["memory_blob"])
                    memory = ProjectMemory.from_dict(data)
                    memory.updated_at = row["updated_at"]
                    memory.last_session_end = row["last_session_end"]

                    # Also load current pointers from DB
                    if row["current_ticket_id"]:
                        memory.current_ticket_id = row["current_ticket_id"]
                    if row["current_plan_id"]:
                        memory.current_plan_id = row["current_plan_id"]

                    return memory
                except Exception:
                    pass  # Return empty memory on parse error

        return ProjectMemory()

    def save(self, memory: ProjectMemory) -> None:
        """Save the project memory.

        Args:
            memory: ProjectMemory to save
        """
        now = datetime.utcnow().isoformat()
        memory.updated_at = now

        # Condense if over budget
        self._condense_if_needed(memory)

        memory_blob = encode(memory.to_dict())

        with self.db.transaction() as conn:
            # Check if exists
            exists = conn.execute(
                "SELECT 1 FROM project_memory WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()

            if exists:
                conn.execute(
                    """
                    UPDATE project_memory
                    SET current_ticket_id = ?, current_plan_id = ?,
                        memory_blob = ?, key_discoveries = ?, available_tools = ?,
                        updated_at = ?
                    WHERE project_id = ?
                    """,
                    (
                        memory.current_ticket_id,
                        memory.current_plan_id,
                        memory_blob,
                        json.dumps([d.content for d in memory.discoveries[:10]]),
                        json.dumps(memory.available_tools),
                        now,
                        self.project_id,
                    ),
                )
            else:
                mem_id = f"mem_{self.project_id}"
                conn.execute(
                    """
                    INSERT INTO project_memory (
                        id, project_id, current_ticket_id, current_plan_id,
                        memory_blob, key_discoveries, available_tools, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mem_id,
                        self.project_id,
                        memory.current_ticket_id,
                        memory.current_plan_id,
                        memory_blob,
                        json.dumps([d.content for d in memory.discoveries[:10]]),
                        json.dumps(memory.available_tools),
                        now,
                    ),
                )

    def set_current_work(
        self,
        ticket_id: Optional[str] = None,
        ticket_title: Optional[str] = None,
        plan_id: Optional[str] = None,
        plan_title: Optional[str] = None,
        plan_status: Optional[str] = None,
    ) -> None:
        """Update the current work pointers.

        Args:
            ticket_id: Current ticket ID
            ticket_title: Current ticket title
            plan_id: Current plan ID
            plan_title: Current plan title
            plan_status: Current plan status
        """
        memory = self.get()

        if ticket_id is not None:
            memory.current_ticket_id = ticket_id
        if ticket_title is not None:
            memory.current_ticket_title = ticket_title
        if plan_id is not None:
            memory.current_plan_id = plan_id
        if plan_title is not None:
            memory.current_plan_title = plan_title
        if plan_status is not None:
            memory.current_plan_status = plan_status

        self.save(memory)

    def update_progress(
        self,
        current_step: Optional[str] = None,
        completed_steps: Optional[int] = None,
        total_steps: Optional[int] = None,
        blockers: Optional[list[str]] = None,
    ) -> None:
        """Update progress tracking.

        Args:
            current_step: Current step description
            completed_steps: Number of completed steps
            total_steps: Total number of steps
            blockers: Current blockers
        """
        memory = self.get()

        if current_step is not None:
            memory.current_step = current_step
        if completed_steps is not None:
            memory.completed_steps = completed_steps
        if total_steps is not None:
            memory.total_steps = total_steps
        if blockers is not None:
            memory.blockers = blockers

        self.save(memory)

    def add_discovery(self, content: str, importance: int = 2, tags: Optional[list[str]] = None) -> None:
        """Add a discovery to memory.

        Discoveries are important findings that should persist across sessions.
        Higher importance (1-5) means the discovery is kept longer during condensation.

        Args:
            content: Discovery content
            importance: 1-5, higher = more important
            tags: Optional categorization tags
        """
        memory = self.get()

        discovery = Discovery(
            content=content,
            importance=max(1, min(5, importance)),
            created_at=datetime.utcnow().isoformat(),
            tags=tags or [],
        )

        memory.discoveries.append(discovery)
        self.save(memory)

    def add_blocker(self, blocker: str) -> None:
        """Add a blocker.

        Args:
            blocker: Blocker description
        """
        memory = self.get()
        if blocker not in memory.blockers:
            memory.blockers.append(blocker)
        self.save(memory)

    def remove_blocker(self, blocker: str) -> None:
        """Remove a resolved blocker.

        Args:
            blocker: Blocker to remove
        """
        memory = self.get()
        memory.blockers = [b for b in memory.blockers if b != blocker]
        self.save(memory)

    def set_tools(self, tools: list[str]) -> None:
        """Set the available tools list.

        Args:
            tools: List of MCP tool names
        """
        memory = self.get()
        memory.available_tools = tools
        self.save(memory)

    def set_files(self, files: list[str]) -> None:
        """Set the key files list.

        Args:
            files: List of important file paths
        """
        memory = self.get()
        memory.key_files = files
        self.save(memory)

    def end_session(self, summary: Optional[str] = None) -> ProjectMemory:
        """End the current session and condense memory.

        Args:
            summary: Optional summary of what was accomplished

        Returns:
            The condensed memory
        """
        memory = self.get()
        now = datetime.utcnow().isoformat()
        memory.last_session_end = now

        # Add summary as discovery if provided
        if summary:
            memory.discoveries.append(Discovery(
                content=f"Session {now[:10]}: {summary}",
                importance=3,
                created_at=now,
            ))

        # Force condensation
        self._condense_if_needed(memory, force=True)

        # Update DB
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE project_memory
                SET last_session_end = ?, memory_blob = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (now, encode(memory.to_dict()), now, self.project_id),
            )

        return memory

    def clear(self) -> None:
        """Clear all memory for this project."""
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE project_memory
                SET current_ticket_id = NULL, current_plan_id = NULL,
                    memory_blob = NULL, key_discoveries = NULL,
                    available_tools = NULL, updated_at = ?
                WHERE project_id = ?
                """,
                (datetime.utcnow().isoformat(), self.project_id),
            )

    def _condense_if_needed(self, memory: ProjectMemory, force: bool = False) -> None:
        """Condense memory if over token budget.

        Condensation rules:
        1. Keep blockers and current work (always)
        2. Sort discoveries by importance, then age
        3. Drop lowest importance + oldest discoveries first
        4. Truncate file/tool lists if still over

        Args:
            memory: Memory to condense
            force: Force condensation even if under budget
        """
        current_tokens = memory.estimate_tokens()

        if not force and current_tokens <= MAX_MEMORY_TOKENS:
            return

        # Sort discoveries: importance desc, then by created_at desc (newest first)
        memory.discoveries.sort(
            key=lambda d: (-d.importance, d.created_at or ""),
            reverse=False,
        )

        # Drop discoveries until under budget
        while memory.estimate_tokens() > MAX_MEMORY_TOKENS and memory.discoveries:
            # Remove lowest importance (last after sort)
            memory.discoveries.pop()

        # If still over, truncate file/tool lists
        if memory.estimate_tokens() > MAX_MEMORY_TOKENS:
            memory.key_files = memory.key_files[:5]
            memory.available_tools = memory.available_tools[:10]

        # If STILL over, truncate blockers (keep most recent)
        if memory.estimate_tokens() > MAX_MEMORY_TOKENS:
            memory.blockers = memory.blockers[-3:]
