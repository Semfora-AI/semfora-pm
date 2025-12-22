"""Shared local ticket operations for CLI and MCP."""

from __future__ import annotations

from typing import Callable, Optional

from ..tickets import Ticket, TicketManager
from ..external_items import ExternalItemsManager
from ..output.pagination import paginate


def format_local_ticket(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "tags": ticket.tags,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "completed_at": ticket.completed_at,
        "parent_ticket_id": ticket.parent_ticket_id,
        "linked_ticket_id": ticket.parent_external_id,
        "linked_ticket_title": ticket.parent_external_title,
        "linked_epic_id": ticket.parent_external_epic_id,
        "linked_epic_name": ticket.parent_external_epic_name,
    }


def format_local_ticket_summary(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "tags": ticket.tags,
        "parent_ticket_id": ticket.parent_ticket_id,
        "linked_ticket_id": ticket.parent_external_id,
        "linked_epic_id": ticket.parent_external_epic_id,
    }


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


def _resolve_local_parent(ticket_manager: TicketManager, parent_ticket_id: str) -> Optional[str]:
    if not parent_ticket_id:
        return None
    ticket = ticket_manager.get(parent_ticket_id)
    if ticket and ticket.source == "local":
        return ticket.id
    if len(parent_ticket_id) == 8:
        matches = [t for t in ticket_manager.list_local(include_completed=True) if t.id.startswith(parent_ticket_id)]
        if len(matches) == 1:
            return matches[0].id
    return None


def create_local_ticket(
    ticket_manager: TicketManager,
    ext_manager: ExternalItemsManager,
    title: str,
    description: Optional[str] = None,
    parent_ticket_id: Optional[str] = None,
    priority: int = 2,
    tags: Optional[list[str]] = None,
    status: str = "pending",
    cache_external: Optional[Callable[[str], Optional[str]]] = None,
) -> dict:
    external_item_id = None
    local_parent_id = None
    if parent_ticket_id:
        local_parent_id = _resolve_local_parent(ticket_manager, parent_ticket_id)
        if not local_parent_id:
            external_item_id = ext_manager.get_uuid_for_provider_id(parent_ticket_id)
            if not external_item_id and cache_external:
                external_item_id = cache_external(parent_ticket_id)

    ticket_id = ticket_manager.create(
        title=title,
        description=description,
        parent_ticket_id=local_parent_id,
        parent_external_item_id=external_item_id,
        priority=priority,
        tags=tags,
        status=status,
        status_category=_status_category(status),
        source="local",
    )
    ticket = ticket_manager.get(ticket_id)
    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}
    return {"success": True, "ticket": format_local_ticket(ticket)}


def update_local_ticket(
    ticket_manager: TicketManager,
    ext_manager: ExternalItemsManager,
    ticket_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    tags: Optional[list[str]] = None,
    parent_ticket_id: Optional[str] = None,
    cache_external: Optional[Callable[[str], Optional[str]]] = None,
) -> dict:
    existing = ticket_manager.get(ticket_id)
    if not existing:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    external_item_id = None
    local_parent_id = None
    if parent_ticket_id is not None:
        if parent_ticket_id == "":
            external_item_id = None
            local_parent_id = None
        else:
            local_parent_id = _resolve_local_parent(ticket_manager, parent_ticket_id)
            if not local_parent_id:
                external_item_id = ext_manager.get_uuid_for_provider_id(parent_ticket_id)
                if not external_item_id and cache_external:
                    external_item_id = cache_external(parent_ticket_id)
                if not external_item_id:
                    return {"error": "ticket_not_found", "message": f"Could not find or cache parent ticket: {parent_ticket_id}"}

    status_category = _status_category(status) if status is not None else None
    ticket = ticket_manager.update(
        ticket_id=ticket_id,
        title=title,
        description=description,
        status=status,
        status_category=status_category,
        priority=priority,
        tags=tags,
        parent_ticket_id=local_parent_id,
        parent_external_item_id=external_item_id,
    )
    return {"success": True, "ticket": format_local_ticket(ticket)}


def list_local_tickets(
    ticket_manager: TicketManager,
    ext_manager: ExternalItemsManager,
    parent_ticket_id: Optional[str] = None,
    epic_id: Optional[str] = None,
    status: Optional[str] = None,
    include_completed: bool = False,
    limit: int = 20,
    offset: int = 0,
    cache_external: Optional[Callable[[str], Optional[str]]] = None,
) -> dict:
    external_item_id = None
    local_parent_id = None
    if parent_ticket_id:
        local_parent_id = _resolve_local_parent(ticket_manager, parent_ticket_id)
        if not local_parent_id:
            external_item_id = ext_manager.get_uuid_for_provider_id(parent_ticket_id)
            if not external_item_id and cache_external:
                external_item_id = cache_external(parent_ticket_id)

    all_tickets = ticket_manager.list_local(
        parent_ticket_id=local_parent_id,
        parent_external_item_id=external_item_id,
        epic_id=epic_id,
        status=status,
        include_completed=include_completed,
    )
    summaries = [format_local_ticket_summary(t) for t in all_tickets]
    page, pagination = paginate(summaries, limit, offset)
    return {"tickets": page, "pagination": pagination}


def get_local_ticket(
    ticket_manager: TicketManager,
    ticket_id: str,
    include_completed: bool = True,
) -> dict:
    ticket = ticket_manager.get(ticket_id)
    if ticket and ticket.source != "local":
        ticket = None

    if not ticket and len(ticket_id) == 8:
        all_tickets = ticket_manager.list_local(include_completed=include_completed)
        matches = [t for t in all_tickets if t.id.startswith(ticket_id)]
        if len(matches) == 1:
            ticket = matches[0]
        elif len(matches) > 1:
            return {
                "error": "ambiguous_id",
                "message": f"Multiple tickets match prefix '{ticket_id}'",
                "matches": [{"id": t.id, "title": t.title} for t in matches],
            }

    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    return {"ticket": format_local_ticket(ticket)}


def delete_local_ticket(
    ticket_manager: TicketManager,
    ticket_id: str,
) -> dict:
    existing = ticket_manager.get(ticket_id)
    if not existing:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    deleted = ticket_manager.delete(ticket_id)
    return {
        "success": deleted,
        "deleted_ticket_id": ticket_id,
        "deleted_title": existing.title,
    }
