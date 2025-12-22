"""Shared service layer for CLI and MCP."""

from .context import resolve_context_info, get_client_for_path, scan_contexts
from .linear_tickets import list_tickets, get_ticket, search_tickets, update_ticket_status
from .projects import (
    list_projects,
    list_labels,
    create_project,
    add_tickets_to_project,
    describe_project,
    show_project,
)
from .labels import list_labels as list_labels_with_colors, audit_labels
from .links import link_blocks, link_related
from .sprints import sprint_status, sprint_suggest, sprint_plan, sprint_status_aggregated
from .local_tickets import (
    format_local_ticket,
    format_local_ticket_summary,
    create_local_ticket,
    update_local_ticket,
    list_local_tickets,
    get_local_ticket,
    delete_local_ticket,
)
from .dependencies import add_dependency, remove_dependency, get_blockers, get_ready_work
from .unified_tickets import (
    format_unified_ticket,
    format_unified_ticket_summary,
    create_unified_ticket,
    get_unified_ticket,
    list_unified_tickets,
    update_unified_ticket,
    link_unified_ticket_external,
    update_unified_ticket_ac,
    add_unified_ticket_ac,
)

__all__ = [
    "resolve_context_info",
    "get_client_for_path",
    "scan_contexts",
    "list_tickets",
    "get_ticket",
    "search_tickets",
    "update_ticket_status",
    "list_projects",
    "list_labels",
    "create_project",
    "add_tickets_to_project",
    "describe_project",
    "show_project",
    "list_labels_with_colors",
    "audit_labels",
    "link_blocks",
    "link_related",
    "sprint_status",
    "sprint_suggest",
    "sprint_plan",
    "sprint_status_aggregated",
    "format_local_ticket",
    "format_local_ticket_summary",
    "create_local_ticket",
    "update_local_ticket",
    "list_local_tickets",
    "get_local_ticket",
    "delete_local_ticket",
    "add_dependency",
    "remove_dependency",
    "get_blockers",
    "get_ready_work",
    "format_unified_ticket",
    "format_unified_ticket_summary",
    "create_unified_ticket",
    "get_unified_ticket",
    "list_unified_tickets",
    "update_unified_ticket",
    "link_unified_ticket_external",
    "update_unified_ticket_ac",
    "add_unified_ticket_ac",
]
