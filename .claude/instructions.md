# Semfora PM - AI Instructions

## Source of Truth: Linear

**Linear is the single source of truth for all tickets.** There are no local YAML files.

All ticket operations MUST go directly through the Linear GraphQL API:
- Creating tickets
- Updating ticket status
- Modifying ticket details
- Querying sprint status
- Managing labels, projects, and relationships

## Workflow

### Creating a Ticket
Use `linear_client.create_issue()` directly. Do NOT create YAML files.

### Updating Ticket Status
Use `linear_client.update_issue()` with the appropriate `state_id`.
Common states: Backlog, Todo, In Progress, In Review, Done

### Querying Tickets
Use `linear_client.get_team_issues()` or GraphQL queries directly.

### Sprint Planning
Query Linear for backlog items, use `update_issue()` to move to Todo state.

## Deprecated Functions

The following are deprecated and should NOT be used:
- `load_tickets()` - was for YAML loading
- `save_tickets()` - was for YAML saving
- `import-csv` command - was for initial import
- `sync push` command - was for YAML→Linear sync
- `sync reconcile` command - was for matching YAML to Linear

## Linear GraphQL API

The `LinearClient` class in `linear_client.py` wraps the GraphQL API. Key methods:
- `create_issue()` - Create new ticket
- `update_issue()` - Update ticket (status, title, description, etc.)
- `get_team_issues()` - List all issues
- `get_team_states()` - Get workflow states (for status updates)
- `create_issue_relation()` - Link tickets (blocks, related)
- `add_issue_to_project()` - Add to a project/milestone

## Example: Marking a Ticket Done

```python
client = LinearClient(config)
states = client.get_team_states(team_id)
done_state_id = states.get("Done")
client.update_issue(issue_id, state_id=done_state_id)
```

## Example: Creating a Ticket

```python
client = LinearClient(config)
issue = client.create_issue(
    title="Implement feature X",
    description="## Overview\n...",
    team_id=team_id,
    priority=2,  # 1=Urgent, 2=High, 3=Medium, 4=Low
    labels=["adk", "north-star"],
    estimate=5,
)
print(f"Created {issue['identifier']}: {issue['url']}")
```
