# Semfora PM v2 - AI Agent Memory System

## Vision

Transform semfora-pm from a Linear integration into a comprehensive AI agent memory system that:
- Provides persistent context across agent sessions
- Tracks acceptance criteria completion automatically
- Surfaces ready-to-work tasks based on dependency resolution
- Syncs bidirectionally with multiple project management providers
- Groups work by project with intelligent cache management

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Agent (Claude, etc.)                  │
├─────────────────────────────────────────────────────────────────┤
│                     Semfora PM MCP Server                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Memory Tools │  │  Plan Tools  │  │  Sync Tools  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
├─────────────────────────────────────────────────────────────────┤
│                     SQLite Local Cache                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Sessions │ │  Plans   │ │ AC Track │ │ Ext Items│          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
├─────────────────────────────────────────────────────────────────┤
│                    Provider Abstraction                         │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌───────────┐            │
│  │ Linear │  │  Jira  │  │ Asana  │  │ Azure ADO │            │
│  └────────┘  └────────┘  └────────┘  └───────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Session Start**: Agent calls `session_start()` → auto-detect project → sync if stale → load memory → return context
2. **During Work**: Agent records decisions/discoveries via `session_note()` → stored in session_events
3. **AC Tracking**: Agent verifies acceptance criteria via `ac_verify()` → evidence stored → progress tracked
4. **Session End**: Agent calls `session_end()` → compact session → extract to long-term memory → push status changes

---

## Database Schema

### Core Tables

```sql
-- ============================================================
-- PROJECT GROUPING
-- Auto-detected from git remote or file path
-- One database file per project for isolation
-- ============================================================
CREATE TABLE projects (
    id TEXT PRIMARY KEY,                    -- Hash of git_remote or path
    name TEXT NOT NULL,                     -- Human-readable name
    path TEXT NOT NULL,                     -- Detection path (git root or folder)
    git_remote TEXT,                        -- Optional: origin URL for cross-machine identification
    provider_type TEXT,                     -- 'linear', 'jira', 'asana', 'azure_ado', NULL for local-only
    provider_project_id TEXT,               -- Provider's project/team ID
    provider_config TEXT,                   -- JSON: provider-specific settings
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TEXT                     -- Last successful sync timestamp
);

-- ============================================================
-- EXTERNAL ITEMS
-- Synced from providers (Linear, Jira, etc.)
-- Read-mostly, updated during sync
-- ============================================================
CREATE TABLE external_items (
    id TEXT PRIMARY KEY,                    -- Internal UUID
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,              -- Provider's unique ID (e.g., SEM-123, PROJ-456)
    item_type TEXT NOT NULL,                -- 'epic', 'ticket', 'subtask', 'sprint', 'milestone'
    title TEXT NOT NULL,
    description TEXT,                       -- Full description/body
    description_html TEXT,                  -- HTML version if available
    status TEXT,                            -- Provider's status value
    status_category TEXT,                   -- Normalized: 'todo', 'in_progress', 'done', 'canceled'
    priority INTEGER,                       -- Normalized 0-4 (0=none, 4=urgent)
    priority_label TEXT,                    -- Provider's priority label
    assignee TEXT,                          -- Assignee identifier
    assignee_name TEXT,                     -- Assignee display name
    labels TEXT,                            -- JSON array of label strings
    parent_id TEXT REFERENCES external_items(id),  -- For subtasks/child items
    sprint_id TEXT,                         -- Current sprint/iteration ID
    sprint_name TEXT,                       -- Sprint/iteration name
    epic_id TEXT,                           -- Parent epic ID
    epic_name TEXT,                         -- Parent epic name
    due_date TEXT,                          -- ISO date
    estimate INTEGER,                       -- Story points or time estimate
    estimate_unit TEXT,                     -- 'points', 'hours', 'days'
    url TEXT,                               -- Direct link to item in provider
    provider_data TEXT,                     -- Full JSON from provider for fields we don't normalize
    created_at_provider TEXT,               -- When created in provider
    updated_at_provider TEXT,               -- When last updated in provider
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, provider_id)
);

-- ============================================================
-- LOCAL PLANS
-- Never synced to providers - agent's private workspace
-- Can be standalone or linked to external items
-- ============================================================
CREATE TABLE local_plans (
    id TEXT PRIMARY KEY,                    -- UUID
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_item_id TEXT REFERENCES external_items(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',          -- 'pending', 'in_progress', 'completed', 'blocked', 'canceled'
    priority INTEGER DEFAULT 0,             -- 0-4, higher = more important
    order_index INTEGER DEFAULT 0,          -- For manual ordering within a group
    tags TEXT,                              -- JSON array for categorization
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT                       -- When marked completed
);

-- ============================================================
-- HIERARCHICAL DEPENDENCIES
-- Flexible relationship system inspired by Beads
-- Supports: blocks, parent_of, discovered_from, related_to
-- ============================================================
CREATE TABLE dependencies (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,              -- 'external' or 'local'
    source_id TEXT NOT NULL,                -- ID in respective table
    target_type TEXT NOT NULL,              -- 'external' or 'local'
    target_id TEXT NOT NULL,                -- ID in respective table
    relation TEXT NOT NULL,                 -- 'blocks', 'parent_of', 'discovered_from', 'related_to'
    strength INTEGER DEFAULT 1,             -- 1=weak, 2=normal, 3=strong (for related_to)
    bidirectional INTEGER DEFAULT 0,        -- 1 if relationship goes both ways
    notes TEXT,                             -- Why this dependency exists
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by_session TEXT,                -- Session that created this
    metadata TEXT,                          -- JSON for additional context
    UNIQUE(source_type, source_id, target_type, target_id, relation)
);

-- ============================================================
-- ACCEPTANCE CRITERIA TRACKING
-- Parsed from ticket descriptions, tracked independently
-- ============================================================
CREATE TABLE acceptance_criteria (
    id TEXT PRIMARY KEY,
    external_item_id TEXT NOT NULL REFERENCES external_items(id) ON DELETE CASCADE,
    criterion_text TEXT NOT NULL,           -- The AC text
    criterion_index INTEGER NOT NULL,       -- Order in original description (0-based)
    source_type TEXT DEFAULT 'parsed',      -- 'parsed', 'manual', 'checklist'
    status TEXT DEFAULT 'pending',          -- 'pending', 'in_progress', 'verified', 'failed', 'blocked'
    verified_at TEXT,
    verified_by_session TEXT,               -- Session ID that verified
    failed_at TEXT,
    failed_reason TEXT,
    evidence TEXT,                          -- JSON: { files: [], tests: [], commits: [], notes: "" }
    attempts INTEGER DEFAULT 0,             -- How many times verification attempted
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- AGENT SESSIONS
-- Tracks work sessions for context persistence
-- ============================================================
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                    -- UUID
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_item_id TEXT REFERENCES external_items(id) ON DELETE SET NULL,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    status TEXT DEFAULT 'active',           -- 'active', 'completed', 'abandoned', 'interrupted'
    summary TEXT,                           -- Compacted summary of what was accomplished
    outcome TEXT,                           -- 'success', 'partial', 'blocked', 'failed'
    outcome_notes TEXT,                     -- Details about the outcome
    context_on_start TEXT,                  -- JSON: what context was loaded at start
    files_modified TEXT,                    -- JSON array of file paths touched
    commits_made TEXT,                      -- JSON array of commit hashes
    duration_seconds INTEGER,               -- Calculated on end
    parent_session_id TEXT REFERENCES sessions(id),  -- For resumed sessions
    metadata TEXT                           -- JSON for additional tracking
);

-- ============================================================
-- SESSION EVENTS
-- Granular tracking within a session
-- ============================================================
CREATE TABLE session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,               -- 'decision', 'discovery', 'progress', 'blocker', 'note', 'error'
    importance INTEGER DEFAULT 1,           -- 1=low, 2=medium, 3=high (for compaction)
    content TEXT NOT NULL,                  -- The actual content
    context TEXT,                           -- JSON: { files: [], symbols: [], related_items: [] }
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- CROSS-SESSION MEMORY
-- Persists after session compaction
-- Decays over time based on importance and access
-- ============================================================
CREATE TABLE memory (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    memory_type TEXT NOT NULL,              -- 'pattern', 'decision', 'architecture', 'preference', 'warning'
    key TEXT NOT NULL,                      -- Unique identifier within type
    content TEXT NOT NULL,                  -- The memory content
    summary TEXT,                           -- Short version for quick recall
    importance INTEGER DEFAULT 1,           -- 1-5, affects decay rate
    confidence REAL DEFAULT 1.0,            -- 0.0-1.0, decreases with contradicting evidence
    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,                        -- Optional: hard expiration
    source_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    source_context TEXT,                    -- JSON: how this memory was derived
    tags TEXT,                              -- JSON array for categorization
    related_items TEXT,                     -- JSON: related external/local items
    UNIQUE(project_id, memory_type, key)
);

-- ============================================================
-- SYNC TRACKING
-- Audit log for all sync operations
-- ============================================================
CREATE TABLE sync_log (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    direction TEXT NOT NULL,                -- 'pull', 'push', 'full'
    status TEXT NOT NULL,                   -- 'started', 'success', 'partial', 'failed'
    provider_type TEXT NOT NULL,
    items_processed INTEGER DEFAULT 0,
    items_created INTEGER DEFAULT 0,
    items_updated INTEGER DEFAULT 0,
    items_deleted INTEGER DEFAULT 0,
    errors TEXT,                            -- JSON array of error messages
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    duration_ms INTEGER,
    metadata TEXT                           -- JSON: additional sync details
);

-- ============================================================
-- PENDING CHANGES
-- Queue for offline changes to push
-- ============================================================
CREATE TABLE pending_changes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL,              -- 'status_update', 'comment', 'assignment'
    external_item_id TEXT NOT NULL REFERENCES external_items(id) ON DELETE CASCADE,
    payload TEXT NOT NULL,                  -- JSON: the change to apply
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    status TEXT DEFAULT 'pending'           -- 'pending', 'synced', 'failed', 'canceled'
);
```

### Indexes for Performance

```sql
-- External items
CREATE INDEX idx_external_items_project ON external_items(project_id);
CREATE INDEX idx_external_items_status ON external_items(status);
CREATE INDEX idx_external_items_status_category ON external_items(status_category);
CREATE INDEX idx_external_items_sprint ON external_items(sprint_id);
CREATE INDEX idx_external_items_epic ON external_items(epic_id);
CREATE INDEX idx_external_items_assignee ON external_items(assignee);
CREATE INDEX idx_external_items_type ON external_items(item_type);
CREATE INDEX idx_external_items_updated ON external_items(updated_at_provider);

-- Local plans
CREATE INDEX idx_local_plans_project ON local_plans(project_id);
CREATE INDEX idx_local_plans_external ON local_plans(external_item_id);
CREATE INDEX idx_local_plans_status ON local_plans(status);

-- Dependencies
CREATE INDEX idx_dependencies_source ON dependencies(source_type, source_id);
CREATE INDEX idx_dependencies_target ON dependencies(target_type, target_id);
CREATE INDEX idx_dependencies_relation ON dependencies(relation);

-- Acceptance criteria
CREATE INDEX idx_ac_external ON acceptance_criteria(external_item_id);
CREATE INDEX idx_ac_status ON acceptance_criteria(status);

-- Sessions
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_active ON sessions(status) WHERE status = 'active';
CREATE INDEX idx_sessions_item ON sessions(external_item_id);
CREATE INDEX idx_sessions_started ON sessions(started_at);

-- Session events
CREATE INDEX idx_events_session ON session_events(session_id);
CREATE INDEX idx_events_type ON session_events(event_type);
CREATE INDEX idx_events_importance ON session_events(importance);

-- Memory
CREATE INDEX idx_memory_project ON memory(project_id);
CREATE INDEX idx_memory_type ON memory(memory_type);
CREATE INDEX idx_memory_key ON memory(project_id, memory_type, key);
CREATE INDEX idx_memory_accessed ON memory(last_accessed);
CREATE INDEX idx_memory_importance ON memory(importance);

-- Sync log
CREATE INDEX idx_sync_project ON sync_log(project_id);
CREATE INDEX idx_sync_status ON sync_log(status);
CREATE INDEX idx_sync_started ON sync_log(started_at);

-- Pending changes
CREATE INDEX idx_pending_project ON pending_changes(project_id);
CREATE INDEX idx_pending_status ON pending_changes(status);
```

---

## MCP Tools - Full Specifications

### Session Management

```python
@mcp.tool()
async def session_start(
    project_path: str | None = None,
    external_item_id: str | None = None,
    resume_last: bool = False
) -> SessionInfo:
    """
    Start or resume an agent work session.

    This is the PRIMARY entry point for agent work. Always call this first.

    Behavior:
    1. Auto-detect project from git remote or path
    2. Check if there's an active session (return it if so)
    3. If resume_last=True, resume most recent interrupted session
    4. Trigger sync if last sync > auto_pull_threshold (default 5 min)
    5. Load relevant memory for context
    6. If external_item_id provided, load full ticket context

    Returns:
        SessionInfo with:
        - session_id: str - Use this for all subsequent calls
        - project: ProjectInfo
        - external_item: TicketInfo | None
        - acceptance_criteria: list[ACInfo] | None
        - blocking_items: list[BlockerInfo]
        - recent_memory: list[MemoryItem]
        - last_session_summary: str | None
        - sync_status: SyncStatus
    """

@mcp.tool()
async def session_end(
    session_id: str,
    summary: str | None = None,
    outcome: Literal["success", "partial", "blocked", "failed"] = "success",
    outcome_notes: str | None = None
) -> SessionSummary:
    """
    End a work session and persist important context.

    This MUST be called when finishing work to ensure memory is saved.

    Behavior:
    1. If summary not provided, auto-generate from session events
    2. Extract high-importance events to long-term memory
    3. Update AC status based on session activity
    4. Push status changes to provider if configured
    5. Calculate session metrics

    Returns:
        SessionSummary with:
        - duration_seconds: int
        - events_count: int
        - memories_created: int
        - ac_verified: int
        - ac_failed: int
        - changes_pushed: int
        - summary: str
    """

@mcp.tool()
async def session_note(
    session_id: str,
    event_type: Literal["decision", "discovery", "progress", "blocker", "note", "error"],
    content: str,
    importance: Literal["low", "medium", "high"] = "medium",
    context: dict | None = None
) -> None:
    """
    Record an event during the current session.

    Call this throughout work to build session history.

    Event types:
    - decision: Choice made about implementation approach
    - discovery: Something learned about the codebase/requirements
    - progress: Work completed (files modified, tests passing)
    - blocker: Something preventing progress
    - note: General observation
    - error: Error encountered and how it was handled

    Context can include:
    - files: list[str] - Related file paths
    - symbols: list[str] - Function/class names
    - related_items: list[str] - External item IDs
    - code_snippet: str - Relevant code
    """

@mcp.tool()
async def get_session_context(
    session_id: str,
    include_events: bool = True,
    include_memory: bool = True,
    include_ac: bool = True,
    events_limit: int = 50
) -> SessionContext:
    """
    Get full context for current session.

    Use this to refresh context mid-session or after resuming.

    Returns:
        SessionContext with:
        - session: SessionInfo
        - events: list[SessionEvent] (if include_events)
        - memory: list[MemoryItem] (if include_memory)
        - acceptance_criteria: list[ACInfo] (if include_ac)
        - blocking_items: list[BlockerInfo]
        - pending_changes: int
    """

@mcp.tool()
async def list_sessions(
    project_path: str | None = None,
    external_item_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0
) -> list[SessionSummary]:
    """
    List past sessions for review.

    Useful for understanding work history on a ticket or project.
    """
```

### Memory Tools

```python
@mcp.tool()
async def memory_store(
    key: str,
    content: str,
    memory_type: Literal["pattern", "decision", "architecture", "preference", "warning"],
    importance: int = 2,
    summary: str | None = None,
    tags: list[str] | None = None,
    related_items: list[str] | None = None,
    project_path: str | None = None
) -> MemoryItem:
    """
    Store a persistent memory item for the project.

    Memory types:
    - pattern: Recurring code pattern or convention
    - decision: Architectural or implementation decision
    - architecture: How the system is structured
    - preference: User/project preferences (formatting, naming, etc.)
    - warning: Things to avoid or be careful about

    Importance (1-5):
    - 1: Nice to know, can be forgotten
    - 2: Useful context (default)
    - 3: Important, keep longer
    - 4: Very important, rarely forget
    - 5: Critical, never forget automatically

    If key already exists, content is updated and access_count resets.
    """

@mcp.tool()
async def memory_recall(
    query: str | None = None,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    min_importance: int = 1,
    limit: int = 10,
    project_path: str | None = None
) -> list[MemoryItem]:
    """
    Recall relevant memories for the current context.

    Search strategies:
    - If query provided: Fuzzy text search on key, content, summary
    - If memory_type provided: Filter to that type
    - If tags provided: Filter to memories with any of those tags
    - Always sorted by relevance * importance * recency

    Returns memories with access_count incremented.
    """

@mcp.tool()
async def memory_update(
    key: str,
    content: str | None = None,
    importance: int | None = None,
    confidence: float | None = None,
    memory_type: str | None = None,
    project_path: str | None = None
) -> MemoryItem:
    """
    Update an existing memory item.

    Use to:
    - Refine content as understanding improves
    - Adjust importance based on relevance
    - Lower confidence when contradicting evidence found
    """

@mcp.tool()
async def memory_forget(
    key: str,
    memory_type: str | None = None,
    project_path: str | None = None
) -> bool:
    """
    Remove a specific memory item.

    Use when memory is wrong or no longer relevant.
    """

@mcp.tool()
async def memory_decay(
    project_path: str | None = None,
    dry_run: bool = True
) -> DecayReport:
    """
    Run memory decay process.

    Automatically called periodically, but can be triggered manually.

    Decay algorithm:
    1. Calculate decay score: days_since_access * (6 - importance) / access_count
    2. Remove memories where decay_score > threshold (default 30)
    3. Never remove importance=5 memories

    If dry_run=True, returns what would be removed without removing.
    """
```

### Local Plans

```python
@mcp.tool()
async def plan_create(
    title: str,
    description: str | None = None,
    external_item_id: str | None = None,
    priority: int = 2,
    tags: list[str] | None = None,
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
    project_path: str | None = None
) -> LocalPlan:
    """
    Create a local plan item.

    Plans are NEVER synced to providers - they're agent-private.

    Use for:
    - Breaking down a ticket into implementation steps
    - Tracking discovered subtasks
    - Personal reminders and notes

    If external_item_id provided, plan is linked to that ticket.
    If blocks/blocked_by provided, creates dependency relationships.
    """

@mcp.tool()
async def plan_update(
    plan_id: str,
    title: str | None = None,
    description: str | None = None,
    status: Literal["pending", "in_progress", "completed", "blocked", "canceled"] | None = None,
    priority: int | None = None,
    tags: list[str] | None = None
) -> LocalPlan:
    """
    Update a local plan item.

    Status transitions:
    - pending → in_progress, blocked, canceled
    - in_progress → completed, blocked, canceled
    - blocked → in_progress, canceled
    - completed/canceled are terminal
    """

@mcp.tool()
async def plan_list(
    external_item_id: str | None = None,
    status: str | None = None,
    tags: list[str] | None = None,
    include_completed: bool = False,
    project_path: str | None = None
) -> list[LocalPlan]:
    """
    List local plans, optionally filtered.

    By default excludes completed/canceled plans.
    """

@mcp.tool()
async def plan_delete(
    plan_id: str
) -> bool:
    """Delete a local plan and its dependencies."""

@mcp.tool()
async def get_ready_work(
    project_path: str | None = None,
    include_external: bool = True,
    include_local: bool = True,
    limit: int = 5
) -> list[ReadyWorkItem]:
    """
    Get unblocked items ready to work on.

    "Ready" means:
    - Status is 'pending' or 'todo'
    - All blocking dependencies are resolved (completed or canceled)
    - For external items: not assigned to someone else (configurable)

    Returns mixed list of external items and local plans, ordered by:
    1. Priority (higher first)
    2. Age (older first)
    3. Type (external before local)
    """
```

### Acceptance Criteria

```python
@mcp.tool()
async def ac_parse(
    external_item_id: str,
    force_reparse: bool = False
) -> list[AcceptanceCriterion]:
    """
    Parse acceptance criteria from ticket description.

    Parsing heuristics (in order of preference):
    1. Explicit "Acceptance Criteria:" or "AC:" section
    2. Checkbox lists: - [ ] or - [x]
    3. Numbered lists in requirements-like sections
    4. Given/When/Then patterns (BDD)
    5. "Must", "Should", "Shall" statements

    If criteria already parsed and force_reparse=False, returns existing.
    If force_reparse=True, deletes existing and reparses.

    Returns parsed criteria with status='pending'.
    """

@mcp.tool()
async def ac_add(
    external_item_id: str,
    criterion_text: str,
    index: int | None = None
) -> AcceptanceCriterion:
    """
    Manually add an acceptance criterion.

    Use when:
    - Parser missed something
    - Discovered implicit requirement
    - Clarified with stakeholder

    If index not provided, appends to end.
    """

@mcp.tool()
async def ac_status(
    external_item_id: str
) -> ACStatus:
    """
    Get status summary of all acceptance criteria for a ticket.

    Returns:
        ACStatus with:
        - total: int
        - pending: int
        - in_progress: int
        - verified: int
        - failed: int
        - blocked: int
        - completion_percentage: float
        - criteria: list[AcceptanceCriterion]
        - blockers: list[str] - IDs of failed/blocked criteria
    """

@mcp.tool()
async def ac_verify(
    criterion_id: str,
    status: Literal["verified", "failed"],
    evidence: dict | None = None,
    notes: str | None = None
) -> AcceptanceCriterion:
    """
    Mark an acceptance criterion as verified or failed.

    Evidence structure:
    {
        "files": ["path/to/file.py"],           # Files that implement this
        "tests": ["test_name", "test_name2"],   # Tests that verify this
        "commits": ["abc123"],                  # Commits related to this
        "screenshots": ["path/to/img.png"],     # Visual evidence
        "notes": "Additional context"
    }

    If status='failed', increment attempts counter.
    """

@mcp.tool()
async def ac_update(
    criterion_id: str,
    criterion_text: str | None = None,
    status: Literal["pending", "in_progress", "verified", "failed", "blocked"] | None = None
) -> AcceptanceCriterion:
    """Update an acceptance criterion's text or status."""

@mcp.tool()
async def ac_check_all(
    external_item_id: str
) -> ACCheckResult:
    """
    Check if all acceptance criteria are satisfied.

    Returns:
        ACCheckResult with:
        - all_verified: bool
        - ready_to_close: bool - All verified AND no blockers
        - summary: str - Human-readable status
        - pending: list[AcceptanceCriterion]
        - failed: list[AcceptanceCriterion]
        - blocked: list[AcceptanceCriterion]
    """
```

### Dependencies

```python
@mcp.tool()
async def dependency_add(
    source_id: str,
    target_id: str,
    relation: Literal["blocks", "parent_of", "discovered_from", "related_to"],
    source_type: Literal["external", "local"] = "external",
    target_type: Literal["external", "local"] = "external",
    notes: str | None = None,
    bidirectional: bool = False
) -> Dependency:
    """
    Add a dependency relationship between items.

    Relation types:
    - blocks: source blocks target (target can't start until source done)
    - parent_of: source is parent of target (hierarchy)
    - discovered_from: source was discovered while working on target
    - related_to: loose relationship (for context)

    If bidirectional=True, creates reverse relationship too.
    """

@mcp.tool()
async def dependency_remove(
    source_id: str,
    target_id: str,
    relation: str | None = None,
    source_type: Literal["external", "local"] = "external",
    target_type: Literal["external", "local"] = "external"
) -> int:
    """
    Remove dependency relationship(s).

    If relation is None, removes ALL relationships between source and target.
    Returns count of removed dependencies.
    """

@mcp.tool()
async def get_blockers(
    item_id: str,
    item_type: Literal["external", "local"] = "external",
    recursive: bool = False,
    include_resolved: bool = False
) -> list[BlockerInfo]:
    """
    Get items blocking this one.

    If recursive=True, walks the full dependency tree (up to depth 10).
    If include_resolved=False, only returns unresolved blockers.

    Returns:
        list[BlockerInfo] with:
        - item: ExternalItem | LocalPlan
        - relation: str
        - depth: int (1 = direct, 2+ = transitive)
        - resolved: bool
        - resolved_at: str | None
    """

@mcp.tool()
async def get_dependents(
    item_id: str,
    item_type: Literal["external", "local"] = "external",
    recursive: bool = False
) -> list[DependentInfo]:
    """
    Get items blocked BY this one (reverse lookup).

    Useful for understanding impact of changes.
    """

@mcp.tool()
async def get_dependency_graph(
    root_id: str | None = None,
    root_type: Literal["external", "local"] = "external",
    max_depth: int = 5,
    project_path: str | None = None
) -> DependencyGraph:
    """
    Get full dependency graph, optionally rooted at an item.

    Returns:
        DependencyGraph with:
        - nodes: list[GraphNode] - All items in graph
        - edges: list[GraphEdge] - All relationships
        - cycles: list[list[str]] - Detected cycles (problematic)
        - orphans: list[str] - Items with no connections
    """
```

### Sync Tools

```python
@mcp.tool()
async def sync_pull(
    project_path: str | None = None,
    full: bool = False,
    item_types: list[str] | None = None
) -> SyncResult:
    """
    Pull updates from external provider.

    By default, incremental sync since last pull.
    Use full=True to resync everything (slow, use sparingly).

    item_types can filter to: ['ticket', 'epic', 'sprint', 'milestone']

    Returns:
        SyncResult with:
        - status: 'success' | 'partial' | 'failed'
        - items_created: int
        - items_updated: int
        - items_deleted: int
        - errors: list[str]
        - duration_ms: int
    """

@mcp.tool()
async def sync_push(
    project_path: str | None = None,
    force: bool = False
) -> SyncResult:
    """
    Push local status changes to provider.

    Only pushes:
    - Status changes
    - Time tracking updates
    - Comments (if enabled)

    NEVER pushes:
    - Local plans
    - Session data
    - Memory
    - Acceptance criteria

    If force=False, only pushes changes older than 5 seconds (debounce).
    """

@mcp.tool()
async def sync_status(
    project_path: str | None = None
) -> SyncStatusInfo:
    """
    Get sync status for the project.

    Returns:
        SyncStatusInfo with:
        - last_pull_at: str | None
        - last_push_at: str | None
        - pending_changes: int
        - is_online: bool
        - last_error: str | None
        - staleness_seconds: int
    """

@mcp.tool()
async def sync_resolve_conflict(
    change_id: str,
    resolution: Literal["keep_local", "keep_remote", "merge"]
) -> bool:
    """
    Resolve a sync conflict.

    Called when provider state differs from local expectation.
    """
```

### Enhanced Existing Tools

```python
@mcp.tool()
async def sprint_status(
    project_path: str | None = None,
    include_ac_status: bool = True,
    include_blockers: bool = True
) -> SprintStatus:
    """
    Get active sprint status.

    ENHANCED from v1:
    - Includes AC completion percentage per ticket
    - Includes blocker count per ticket
    - Groups by status category (todo/in_progress/done)

    Returns:
        SprintStatus with:
        - sprint: SprintInfo
        - tickets: list[SprintTicket] with ac_completion and blocker_count
        - summary: { todo: int, in_progress: int, done: int }
        - velocity: { completed_points: int, remaining_points: int }
    """

@mcp.tool()
async def get_ticket(
    identifier: str,
    include_plans: bool = True,
    include_ac: bool = True,
    include_memory: bool = True,
    include_history: bool = False
) -> TicketDetail:
    """
    Get full ticket details.

    ENHANCED from v1:
    - Includes local plans linked to ticket
    - Includes acceptance criteria with status
    - Includes related memory items
    - Optionally includes session history

    Returns:
        TicketDetail with all the context an agent needs.
    """

@mcp.tool()
async def sprint_suggest(
    project_path: str | None = None,
    consider_blockers: bool = True,
    consider_ac_complexity: bool = True,
    prefer_assigned: bool = True,
    limit: int = 3
) -> list[SuggestedTicket]:
    """
    Suggest next ticket to work on.

    ENHANCED from v1:
    - Considers dependency resolution (blocked tickets deprioritized)
    - Considers AC complexity (simpler tickets for quick wins)
    - Considers recent memory (related work prioritized)
    - Considers assignment (your tickets first)

    Returns tickets with explanation of why suggested.
    """

@mcp.tool()
async def update_ticket_status(
    identifier: str,
    status: str,
    add_comment: str | None = None,
    queue_if_offline: bool = True
) -> TicketInfo:
    """
    Update ticket status in provider.

    ENHANCED from v1:
    - Queues change if offline (syncs when back online)
    - Optionally adds comment explaining status change
    - Validates status transition is valid for provider

    Status values depend on provider configuration.
    """
```

---

## Cross-Platform Cache Location

### Implementation

```python
from platformdirs import user_cache_dir, user_config_dir
from pathlib import Path
import os

def get_cache_dir() -> Path:
    """
    Get platform-appropriate cache directory.

    Priority:
    1. SEMFORA_PM_CACHE_DIR environment variable
    2. Config file setting
    3. platformdirs default
    """
    # Check environment variable first
    if env_dir := os.environ.get("SEMFORA_PM_CACHE_DIR"):
        path = Path(env_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Check config file
    config_dir = Path(user_config_dir("semfora-pm", "Semfora"))
    config_file = config_dir / "config.json"
    if config_file.exists():
        import json
        with open(config_file) as f:
            config = json.load(f) or {}
        if cache_dir := config.get("cache_dir"):
            path = Path(cache_dir)
            path.mkdir(parents=True, exist_ok=True)
            return path

    # Use platformdirs default
    path = Path(user_cache_dir("semfora-pm", "Semfora"))
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_project_db_path(project_id: str) -> Path:
    """Get database path for a specific project."""
    projects_dir = get_cache_dir() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir / f"{project_id}.db"

def get_global_db_path() -> Path:
    """Get path to global database (cross-project data)."""
    return get_cache_dir() / "global.db"
```

### Platform Locations

| Platform | Default Cache Location |
|----------|------------------------|
| Linux | `~/.cache/semfora-pm/` |
| macOS | `~/Library/Caches/semfora-pm/` |
| Windows | `C:\Users\<user>\AppData\Local\Semfora\semfora-pm\Cache\` |

### Directory Structure

```
<cache_dir>/
├── global.db                    # Cross-project data (project registry)
├── projects/
│   ├── <project_id_1>.db        # Per-project database
│   ├── <project_id_2>.db
│   └── ...
├── logs/
│   └── sync.log                 # Sync operation logs
└── temp/
    └── ...                      # Temporary files during sync
```

---

## Provider Abstraction

### Interface Definition

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

class ItemType(Enum):
    EPIC = "epic"
    TICKET = "ticket"
    SUBTASK = "subtask"
    SPRINT = "sprint"
    MILESTONE = "milestone"

class StatusCategory(Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELED = "canceled"

@dataclass
class ProviderItem:
    """Normalized item from any provider."""
    provider_id: str
    item_type: ItemType
    title: str
    description: str | None
    status: str                      # Provider's raw status
    status_category: StatusCategory  # Normalized category
    priority: int                    # Normalized 0-4
    assignee: str | None
    labels: list[str]
    parent_id: str | None
    sprint_id: str | None
    epic_id: str | None
    due_date: datetime | None
    estimate: int | None
    url: str
    created_at: datetime
    updated_at: datetime
    raw_data: dict                   # Full provider response

@dataclass
class ProviderSprint:
    """Normalized sprint/iteration."""
    provider_id: str
    name: str
    status: str                      # 'active', 'planned', 'completed'
    start_date: datetime | None
    end_date: datetime | None
    goal: str | None

@dataclass
class ItemUpdate:
    """Update to send to provider."""
    status: str | None = None
    assignee: str | None = None
    priority: int | None = None
    labels: list[str] | None = None
    comment: str | None = None

class ProviderInterface(ABC):
    """Abstract interface for project management providers."""

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider identifier: 'linear', 'jira', 'asana', 'azure_ado'."""

    @abstractmethod
    async def authenticate(self, config: dict) -> None:
        """
        Authenticate with the provider.

        Config varies by provider:
        - linear: { api_key: str }
        - jira: { url: str, email: str, api_token: str }
        - asana: { access_token: str }
        - azure_ado: { organization: str, project: str, pat: str }
        """

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if connection is working."""

    @abstractmethod
    async def get_projects(self) -> list[dict]:
        """List accessible projects/teams."""

    @abstractmethod
    async def get_items(
        self,
        project_id: str,
        since: datetime | None = None,
        item_types: list[ItemType] | None = None
    ) -> AsyncIterator[ProviderItem]:
        """
        Stream items from provider.

        If since provided, only return items updated after that time.
        """

    @abstractmethod
    async def get_item(self, item_id: str) -> ProviderItem:
        """Get single item by provider ID."""

    @abstractmethod
    async def update_item(
        self,
        item_id: str,
        update: ItemUpdate
    ) -> ProviderItem:
        """Update item in provider. Returns updated item."""

    @abstractmethod
    async def get_sprints(
        self,
        project_id: str,
        status: str | None = None
    ) -> list[ProviderSprint]:
        """Get sprints/iterations for project."""

    @abstractmethod
    def normalize_status(self, raw_status: str) -> StatusCategory:
        """Convert provider status to normalized category."""

    @abstractmethod
    def get_status_options(self, project_id: str) -> list[str]:
        """Get valid status values for transitions."""
```

### Provider Registry

```python
class ProviderRegistry:
    """Factory for provider instances."""

    _providers: dict[str, type[ProviderInterface]] = {}

    @classmethod
    def register(cls, provider_type: str):
        """Decorator to register a provider implementation."""
        def decorator(provider_class: type[ProviderInterface]):
            cls._providers[provider_type] = provider_class
            return provider_class
        return decorator

    @classmethod
    def get(cls, provider_type: str, config: dict) -> ProviderInterface:
        """Get configured provider instance."""
        if provider_type not in cls._providers:
            raise ValueError(f"Unknown provider: {provider_type}")
        provider = cls._providers[provider_type]()
        # Authentication happens lazily
        return provider

    @classmethod
    def available_providers(cls) -> list[str]:
        """List registered provider types."""
        return list(cls._providers.keys())

# Register providers
@ProviderRegistry.register("linear")
class LinearProvider(ProviderInterface):
    ...

@ProviderRegistry.register("jira")
class JiraProvider(ProviderInterface):
    ...

@ProviderRegistry.register("asana")
class AsanaProvider(ProviderInterface):
    ...

@ProviderRegistry.register("azure_ado")
class AzureADOProvider(ProviderInterface):
    ...
```

---

## Hybrid Sync Strategy

### Auto-Sync Configuration

```json
# .pm/config.json
sync:
  # Pull settings
  auto_pull_on_session_start: true
  auto_pull_threshold_seconds: 300  # 5 minutes
  pull_item_types:
    - ticket
    - sprint
    - epic

  # Push settings
  auto_push_on_session_end: true
  auto_push_on_status_change: true
  push_debounce_seconds: 5

  # Offline settings
  queue_changes_when_offline: true
  max_queued_changes: 100
  retry_interval_seconds: 60
```

### Sync Flow

```
Session Start
    │
    ▼
┌─────────────────┐
│ Check last sync │
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Stale?  │──No──► Continue
    └────┬────┘
         │Yes
         ▼
┌─────────────────┐
│ Check network   │
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │Online?  │──No──► Mark offline, continue
    └────┬────┘
         │Yes
         ▼
┌─────────────────┐
│ Pull changes    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Apply to cache  │
└────────┬────────┘
         │
         ▼
    Continue
```

### Conflict Resolution

| Field | Strategy | Rationale |
|-------|----------|-----------|
| title | Provider wins | Authoritative source |
| description | Provider wins | May have updates from others |
| status | Merge with notification | Both may have changed |
| assignee | Provider wins | Assignment changes externally |
| labels | Provider wins | Team categorization |
| AC status | Local wins | Agent-specific tracking |
| Local plans | Never conflicts | Not synced |
| Memory | Never conflicts | Not synced |

### Offline Behavior

```python
class SyncManager:
    async def handle_offline_change(self, change: PendingChange):
        """Queue change for later sync."""
        async with self.db.transaction():
            await self.db.insert("pending_changes", change)

    async def process_pending_changes(self):
        """Called when back online."""
        pending = await self.db.query(
            "SELECT * FROM pending_changes WHERE status = 'pending' ORDER BY created_at"
        )

        for change in pending:
            try:
                await self.provider.update_item(
                    change.external_item_id,
                    change.payload
                )
                change.status = "synced"
            except ConflictError as e:
                # Surface to user for resolution
                await self.notify_conflict(change, e)
            except Exception as e:
                change.attempts += 1
                change.last_error = str(e)
                if change.attempts >= 5:
                    change.status = "failed"

            await self.db.update("pending_changes", change)
```

---

## Implementation Phases - Detailed

### Phase 1: Foundation (Week 1-2)

**Goal**: Core infrastructure without breaking existing functionality

#### Tasks

1. **Add dependencies** (`pyproject.toml`)
   ```toml
   dependencies = [
       "platformdirs>=4.0",
       "aiosqlite>=0.19",
       "rapidfuzz>=3.0",
   ]
   ```

2. **Create database module** (`src/semfora_pm/db/`)
   - `schema.py` - All CREATE TABLE statements
   - `migrations.py` - Version tracking and migration runner
   - `connection.py` - Connection pooling with aiosqlite

3. **Create project detection** (`src/semfora_pm/project_detect.py`)
   - Parse git remote URL
   - Hash to create stable project ID
   - Fallback to path-based detection

4. **Create sync base** (`src/semfora_pm/sync/base.py`)
   - SyncManager class
   - Sync logging
   - Change queuing

5. **Migration for existing users**
   - Detect existing Linear-only usage
   - Create project entry from current config
   - Preserve any existing local state

#### Files to Create

```
src/semfora_pm/
├── db/
│   ├── __init__.py
│   ├── schema.py          # Schema definitions
│   ├── migrations.py      # Migration system
│   └── connection.py      # Connection pool
├── project_detect.py      # Project auto-detection
└── sync/
    ├── __init__.py
    └── base.py            # Sync infrastructure
```

#### Tests

- [ ] Project detection from git remote
- [ ] Project detection from path
- [ ] Database creation and migration
- [ ] Connection pooling behavior
- [ ] Sync log recording

---

### Phase 2: Local Plans & Dependencies (Week 2-3)

**Goal**: Local-only planning features

#### Tasks

1. **Implement local plans** (`src/semfora_pm/plans.py`)
   - CRUD operations
   - Linking to external items
   - Status management

2. **Implement dependencies** (`src/semfora_pm/dependencies.py`)
   - Add/remove relationships
   - Blocker resolution
   - Graph traversal

3. **Implement ready-work detection**
   - Query for unblocked items
   - Priority sorting
   - Mix external and local

4. **Add MCP tools**
   - `plan_create`, `plan_update`, `plan_list`, `plan_delete`
   - `dependency_add`, `dependency_remove`
   - `get_blockers`, `get_dependents`, `get_dependency_graph`
   - `get_ready_work`

#### Files to Create

```
src/semfora_pm/
├── plans.py               # Local plan management
└── dependencies.py        # Dependency graph
```

#### Tests

- [ ] Plan CRUD operations
- [ ] Plan linking to external items
- [ ] Dependency creation and removal
- [ ] Blocker detection
- [ ] Transitive dependency resolution
- [ ] Ready-work filtering
- [ ] Cycle detection in dependencies

---

### Phase 3: Session & Memory (Week 3-4)

**Goal**: Agent context persistence

#### Tasks

1. **Implement session management** (`src/semfora_pm/session.py`)
   - Start/end lifecycle
   - Event recording
   - Context loading

2. **Implement memory system** (`src/semfora_pm/memory.py`)
   - Store/recall with fuzzy search
   - Importance-based sorting
   - Access tracking

3. **Implement memory compaction** (`src/semfora_pm/compaction.py`)
   - Extract important events to memory
   - Decay algorithm
   - Cleanup routines

4. **Add MCP tools**
   - `session_start`, `session_end`, `session_note`
   - `get_session_context`, `list_sessions`
   - `memory_store`, `memory_recall`, `memory_update`, `memory_forget`
   - `memory_decay`

#### Files to Create

```
src/semfora_pm/
├── session.py             # Session lifecycle
├── memory.py              # Memory operations
└── compaction.py          # Decay and cleanup
```

#### Tests

- [ ] Session start creates proper context
- [ ] Session events are recorded
- [ ] Session end compacts properly
- [ ] Memory store/recall works
- [ ] Fuzzy search finds relevant memories
- [ ] Memory decay removes old items
- [ ] High-importance memories persist

---

### Phase 4: Acceptance Criteria (Week 4-5)

**Goal**: Automatic AC tracking

#### Tasks

1. **Implement AC parser** (`src/semfora_pm/ac_parser.py`)
   - Pattern recognition (checkboxes, numbered lists, BDD)
   - Section detection
   - Deduplication

2. **Implement AC tracker** (`src/semfora_pm/ac_tracker.py`)
   - Status management
   - Evidence storage
   - Completion checking

3. **Integrate with tickets**
   - Auto-parse on ticket fetch
   - Include AC in ticket detail
   - Include completion % in sprint status

4. **Add MCP tools**
   - `ac_parse`, `ac_add`
   - `ac_status`, `ac_verify`, `ac_update`
   - `ac_check_all`

#### Files to Create

```
src/semfora_pm/
├── ac_parser.py           # AC extraction
└── ac_tracker.py          # AC management
```

#### Tests

- [ ] Parse checkbox lists
- [ ] Parse numbered lists
- [ ] Parse BDD Given/When/Then
- [ ] Parse explicit AC sections
- [ ] Verify/fail updates status
- [ ] Evidence is stored correctly
- [ ] Completion calculation is accurate

---

### Phase 5: Provider Abstraction (Week 5-6)

**Goal**: Multi-provider support

#### Tasks

1. **Create provider interface** (`src/semfora_pm/providers/base.py`)
   - Abstract base class
   - Normalized data structures
   - Registry pattern

2. **Refactor Linear** (`src/semfora_pm/providers/linear.py`)
   - Implement interface
   - Preserve existing functionality
   - Add missing methods

3. **Stub other providers**
   - Jira: Auth + basic item fetch
   - Asana: Auth + basic item fetch
   - Azure ADO: Auth + basic item fetch

4. **Update sync manager**
   - Use provider interface
   - Handle provider-specific quirks

#### Files to Create

```
src/semfora_pm/providers/
├── __init__.py
├── base.py                # Interface definition
├── linear.py              # Linear implementation
├── jira.py                # Jira stub
├── asana.py               # Asana stub
├── azure_ado.py           # Azure DevOps stub
└── registry.py            # Provider factory
```

#### Tests

- [ ] Provider interface contract
- [ ] Linear provider works (existing tests)
- [ ] Provider registry returns correct type
- [ ] Status normalization works per provider
- [ ] Sync works through abstraction

---

### Phase 6: Polish & Integration (Week 6-7)

**Goal**: Production readiness

#### Tasks

1. **Error handling**
   - Graceful degradation
   - User-friendly error messages
   - Automatic retry with backoff

2. **Sync improvements**
   - Conflict resolution UI hints
   - Offline mode indicators
   - Sync progress reporting

3. **Performance**
   - Query optimization
   - Connection pooling tuning
   - Index verification

4. **Documentation**
   - Updated README
   - MCP tool reference
   - Configuration guide

5. **Testing**
   - Integration tests
   - Load tests
   - Offline scenario tests

6. **CLAUDE.md update**
   - New tool usage instructions
   - Session workflow guidelines
   - Memory best practices

#### Files to Modify

- `README.md` - Full documentation
- `CLAUDE.md` - Agent instructions
- All modules - Error handling improvements

---

## Configuration Files

### Project Config (`.pm/config.json`)

```json
# Project-specific configuration
# Located in project root

# Provider settings
provider: linear
provider_config:
  team_id: "YOUR_TEAM_ID"
  # For Jira:
  # url: https://company.atlassian.net
  # project_key: PROJ

# Sync settings
sync:
  auto_pull_on_session_start: true
  auto_pull_threshold_seconds: 300
  auto_push_on_session_end: true
  auto_push_on_status_change: true
  push_debounce_seconds: 5
  queue_changes_when_offline: true

# Memory settings
memory:
  max_items_per_type: 100
  decay_after_days: 30
  importance_threshold: 2
  auto_decay_on_session_end: true

# Session settings
session:
  auto_generate_summary: true
  max_events_before_compaction: 1000
  warn_on_unended_session: true

# AC settings
acceptance_criteria:
  auto_parse: true
  patterns:
    - "AC:"
    - "Acceptance Criteria:"
    - "- [ ]"
    - "Given/When/Then"
  require_evidence_for_verification: false
```

### Global Config (`~/.config/semfora-pm/config.json`)

```json
# User-wide configuration
# Applies to all projects unless overridden

# Cache location (optional override)
# cache_dir: /custom/path

# Default provider credentials
providers:
  linear:
    api_key: ${LINEAR_API_KEY}
  jira:
    url: https://company.atlassian.net
    email: ${JIRA_EMAIL}
    api_token: ${JIRA_TOKEN}
  asana:
    access_token: ${ASANA_TOKEN}
  azure_ado:
    organization: ${ADO_ORG}
    pat: ${ADO_PAT}

# Global defaults
defaults:
  provider: linear
  sync:
    auto_pull_threshold_seconds: 300
  memory:
    max_items_per_type: 100
```

---

## Dependencies

```toml
[project]
dependencies = [
    # Existing
    "mcp>=1.0",
    "httpx>=0.25",
    "pydantic>=2.0",
        "click>=8.0",

    # New for v2
    "platformdirs>=4.0",     # Cross-platform cache paths
    "aiosqlite>=0.19",       # Async SQLite
    "rapidfuzz>=3.0",        # Fuzzy text search for memory
]

[project.optional-dependencies]
jira = ["jira>=3.5"]         # Jira provider
asana = ["asana>=5.0"]       # Asana provider
azure = ["azure-devops>=7"]  # Azure DevOps provider
all = ["jira>=3.5", "asana>=5.0", "azure-devops>=7"]
```

---

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Memory Persistence | Agent resumes with full context | Manual testing across sessions |
| AC Coverage | 100% of ticket ACs parsed | Count parsed vs manual inspection |
| Ready Work Accuracy | 0 suggested tasks have unresolved blockers | Query validation |
| Sync Reliability | < 1% sync failures | Sync log analysis |
| Session Start Time | < 500ms | Benchmark |
| Memory Recall Time | < 100ms | Benchmark |
| Offline Support | Changes queue and sync | Manual testing |

---

## Migration Path

### For Existing Users

1. **Automatic migration on first run**
   - Detect existing `.pm/config.json`
   - Create project database
   - Import project settings

2. **No breaking changes to existing tools**
   - `sprint_status`, `get_ticket`, etc. work unchanged
   - New features are additive

3. **Gradual adoption**
   - Start using sessions when ready
   - Memory accumulates over time
   - AC tracking opt-in per ticket

### Breaking Changes (if any)

None planned. All new features are additive to existing API.

---

## Open Questions

1. **Memory Search**: Use SQLite FTS5 for better text search, or keep rapidfuzz for simplicity?
   - Recommendation: Start with rapidfuzz, add FTS5 if needed

2. **Session Timeout**: How long before abandoned session auto-closes?
   - Recommendation: 24 hours, with warning on next session start

3. **AC Evidence Format**: Standardize or keep flexible JSON?
   - Recommendation: Flexible JSON with suggested schema

4. **Provider Priority**: After Linear, which provider next?
   - Recommendation: Jira (most common enterprise tool)

5. **Multi-project Sync**: Support syncing one local project to multiple providers?
   - Recommendation: Not in v2, consider for v3
