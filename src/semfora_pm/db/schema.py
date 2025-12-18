"""Database schema definitions and migrations for semfora-pm local storage."""

SCHEMA_VERSION = 3

# Initial schema (version 1)
SCHEMA_V1 = """
-- ============================================================
-- PROJECTS TABLE
-- Auto-detected from .pm/config.yaml location
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config_path TEXT NOT NULL UNIQUE,
    provider TEXT DEFAULT 'linear',
    provider_team_id TEXT,
    provider_project_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- EXTERNAL ITEMS (Cached Provider Tickets)
-- Synced copies for linking, not authoritative
-- ============================================================
CREATE TABLE IF NOT EXISTS external_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,              -- Provider identifier (e.g., "SEM-123")
    item_type TEXT DEFAULT 'ticket',        -- 'ticket', 'epic', 'subtask'
    title TEXT NOT NULL,
    description TEXT,
    status TEXT,                            -- Provider's status value
    status_category TEXT,                   -- Normalized: 'todo', 'in_progress', 'done', 'canceled'
    priority INTEGER,                       -- 0-4 (0=none, 4=urgent)
    assignee TEXT,
    assignee_name TEXT,
    labels TEXT,                            -- JSON array of label strings
    epic_id TEXT,                           -- Parent epic ID for grouping
    epic_name TEXT,                         -- Parent epic name
    sprint_id TEXT,
    sprint_name TEXT,
    url TEXT,
    provider_data TEXT,                     -- Full JSON from provider
    created_at_provider TEXT,
    updated_at_provider TEXT,
    cached_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, provider_id)
);

-- ============================================================
-- LOCAL PLANS
-- Never synced to providers - agent's private workspace
-- ============================================================
CREATE TABLE IF NOT EXISTS local_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    external_item_id TEXT REFERENCES external_items(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',          -- pending, in_progress, completed, blocked, canceled, orphaned
    priority INTEGER DEFAULT 2,             -- 0-4, higher = more important
    order_index INTEGER DEFAULT 0,          -- For manual ordering
    tags TEXT,                              -- JSON array for categorization
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

-- ============================================================
-- DEPENDENCIES
-- Relationships between items (local and external)
-- ============================================================
CREATE TABLE IF NOT EXISTS dependencies (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,              -- 'external' or 'local'
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,              -- 'external' or 'local'
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,                 -- 'blocks', 'related_to'
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id, target_type, target_id, relation)
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_external_items_project ON external_items(project_id);
CREATE INDEX IF NOT EXISTS idx_external_items_provider_id ON external_items(project_id, provider_id);
CREATE INDEX IF NOT EXISTS idx_external_items_epic ON external_items(epic_id);
CREATE INDEX IF NOT EXISTS idx_external_items_status ON external_items(status_category);

CREATE INDEX IF NOT EXISTS idx_local_plans_project ON local_plans(project_id);
CREATE INDEX IF NOT EXISTS idx_local_plans_external ON local_plans(external_item_id);
CREATE INDEX IF NOT EXISTS idx_local_plans_status ON local_plans(status);

CREATE INDEX IF NOT EXISTS idx_dependencies_source ON dependencies(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_target ON dependencies(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_relation ON dependencies(relation);
"""

# Schema V2: Add sync columns to external_items for local-first tickets
SCHEMA_V2_MIGRATION = """
-- ============================================================
-- V2: Add sync support to external_items
-- Enables local ticket creation with optional Linear sync
-- ============================================================

-- Source of the item: where did it originate?
-- 'linear': Pulled from Linear (default for existing rows)
-- 'local': Created locally, not yet pushed to Linear
-- 'synced': Created locally, successfully pushed to Linear
ALTER TABLE external_items ADD COLUMN source TEXT DEFAULT 'linear';

-- Sync status: current state of synchronization
-- 'synced': In sync with Linear (or local-only with no sync needed)
-- 'pending_push': Local changes need to be pushed to Linear
-- 'pending_pull': Linear has newer changes (detected during sync)
-- 'conflict': Both local and Linear changed since last sync
ALTER TABLE external_items ADD COLUMN sync_status TEXT DEFAULT 'synced';

-- Linear's internal UUID (different from provider_id which is "SEM-123")
-- Needed for update_issue() API calls
ALTER TABLE external_items ADD COLUMN linear_id TEXT;

-- Direct link to the Linear issue
ALTER TABLE external_items ADD COLUMN linear_url TEXT;

-- Indexes for sync queries
CREATE INDEX IF NOT EXISTS idx_external_items_source ON external_items(source);
CREATE INDEX IF NOT EXISTS idx_external_items_sync_status ON external_items(sync_status);
"""

# Schema V3: Rename local_plans to local_tickets (nomenclature cleanup)
SCHEMA_V3_MIGRATION = """
-- ============================================================
-- V3: Rename local_plans to local_tickets
-- Unify nomenclature: everything is tickets, sub-tickets, epics
-- ============================================================

-- Create new table with updated column name
CREATE TABLE IF NOT EXISTS local_tickets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_ticket_id TEXT REFERENCES external_items(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 2,
    order_index INTEGER DEFAULT 0,
    tags TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

-- Copy data from old table if it exists
INSERT OR IGNORE INTO local_tickets (id, project_id, parent_ticket_id, title, description, status, priority, order_index, tags, created_at, updated_at, completed_at)
SELECT id, project_id, external_item_id, title, description, status, priority, order_index, tags, created_at, updated_at, completed_at
FROM local_plans;

-- Drop old table
DROP TABLE IF EXISTS local_plans;

-- Create indexes for new table
CREATE INDEX IF NOT EXISTS idx_local_tickets_project ON local_tickets(project_id);
CREATE INDEX IF NOT EXISTS idx_local_tickets_parent ON local_tickets(parent_ticket_id);
CREATE INDEX IF NOT EXISTS idx_local_tickets_status ON local_tickets(status);
"""


def get_migration_sql(from_version: int, to_version: int) -> list[str]:
    """Get SQL statements to migrate from one version to another.

    Args:
        from_version: Current schema version (0 for fresh install)
        to_version: Target schema version

    Returns:
        List of SQL scripts to execute in order
    """
    migrations = []

    if from_version < 1 <= to_version:
        migrations.append(SCHEMA_V1)

    if from_version < 2 <= to_version:
        migrations.append(SCHEMA_V2_MIGRATION)

    if from_version < 3 <= to_version:
        migrations.append(SCHEMA_V3_MIGRATION)

    return migrations
