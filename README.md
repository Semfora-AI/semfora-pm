# Semfora PM

Project management CLI for Semfora - manages tickets as YAML files and syncs them to Linear.

## Features

- **YAML-based tickets**: Define tickets in version-controlled YAML files
- **Linear sync**: Push tickets to Linear with proper labels (not comma-separated!)
- **Bidirectional tracking**: Linear IDs saved back to YAML after sync
- **Component organization**: Tickets organized by component (engine, adk, cli)
- **Phase tracking**: Track implementation phases and dependencies

## Installation

```bash
cd semfora-pm
pip install -e .
```

## Quick Start

### 1. Configure Linear API

Get your API key from Linear Settings → API → Personal API keys.

```bash
semfora-pm auth setup
# Enter your API key when prompted
```

### 2. Import existing CSV tickets

```bash
# Import engine tickets
semfora-pm import-csv ../linear-import/semfora-engine-tasks.csv -c engine

# Import ADK tickets
semfora-pm import-csv ../linear-import/semfora-adk-tasks.csv -c adk

# Import CLI tickets
semfora-pm import-csv ../linear-import/semfora-cli-tasks.csv -c cli
```

### 3. Push to Linear

```bash
# Dry run first
semfora-pm sync push --dry-run

# Push all tickets
semfora-pm sync push

# Push specific component
semfora-pm sync push -c engine

# Push to a specific project
semfora-pm sync push -p "Semfora"
```

## Commands

### Authentication

```bash
semfora-pm auth setup     # Configure API key
semfora-pm auth status    # Check authentication
```

### Tickets

```bash
semfora-pm list                    # List all tickets
semfora-pm list -c engine          # Filter by component
semfora-pm list --not-synced       # Show unsynced tickets
semfora-pm show engine-001         # Show ticket details
```

### Sync

```bash
semfora-pm sync push              # Push tickets to Linear
semfora-pm sync push --dry-run    # Preview changes
semfora-pm sync status            # Show sync status
```

### Projects

```bash
semfora-pm project list           # List Linear projects
semfora-pm project labels         # List available labels
```

## Ticket YAML Format

Tickets are stored in `tickets/{component}.yaml`:

```yaml
tickets:
  - id: engine-001
    title: Implement incremental re-indexing
    description: |
      ## Overview
      Add ability to update the semantic index incrementally...
    component: engine
    priority: 2
    status: Backlog
    labels:
      - indexing
      - north-star
    estimate: 8
    phase: phase-2
    depends_on: []
    blocks:
      - engine-003
    linear_id: null  # Populated after sync
    linear_url: null
```

## Environment Variables

- `LINEAR_API_KEY`: Linear API key (alternative to config file)

## Configuration

Config stored at `~/.config/semfora-pm/config.json`:

```json
{
  "api_key": "lin_api_...",
  "team_id": "...",
  "project_id": "..."
}
```
# semforma-pm
