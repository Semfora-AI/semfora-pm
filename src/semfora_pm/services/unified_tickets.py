"""Shared unified ticket operations for CLI and MCP."""

from __future__ import annotations

from typing import Optional

from ..tickets import TicketManager, Ticket, TicketSummary
from ..output.pagination import build_pagination


def format_unified_ticket(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "source": ticket.source,
        "external_id": ticket.external_id,
        "external_url": ticket.external_url,
        "parent_ticket_id": ticket.parent_ticket_id,
        "parent_external_item_id": ticket.parent_external_item_id,
        "parent_external_id": ticket.parent_external_id,
        "parent_external_title": ticket.parent_external_title,
        "parent_external_epic_id": ticket.parent_external_epic_id,
        "parent_external_epic_name": ticket.parent_external_epic_name,
        "description": ticket.description,
        "status": ticket.status,
        "status_category": ticket.status_category,
        "priority": ticket.priority,
        "order_index": ticket.order_index,
        "acceptance_criteria": [
            {
                "index": ac.index,
                "text": ac.text,
                "status": ac.status,
                "evidence": ac.evidence,
            }
            for ac in ticket.acceptance_criteria
        ],
        "labels": ticket.labels,
        "tags": ticket.tags,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "completed_at": ticket.completed_at,
    }


def format_unified_ticket_summary(ticket: TicketSummary) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "source": ticket.source,
        "status": ticket.status,
        "status_category": ticket.status_category,
        "priority": ticket.priority,
        "external_id": ticket.external_id,
        "has_ac": ticket.has_ac,
    }


def create_unified_ticket(
    ticket_manager: TicketManager,
    title: str,
    description: Optional[str] = None,
    acceptance_criteria: Optional[list[str]] = None,
    priority: int = 2,
    labels: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    ticket_id = ticket_manager.create(
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria,
        priority=priority,
        labels=labels,
        tags=tags,
    )

    ticket = ticket_manager.get(ticket_id)
    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    return {
        "success": True,
        "ticket": format_unified_ticket(ticket),
    }


def get_unified_ticket(ticket_manager: TicketManager, ticket_id: str) -> dict:
    ticket = ticket_manager.get(ticket_id)
    if not ticket:
        ticket = ticket_manager.get_by_external_id(ticket_id)

    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    return {"ticket": format_unified_ticket(ticket)}


def list_unified_tickets(
    ticket_manager: TicketManager,
    source: Optional[str] = None,
    status: Optional[str] = None,
    status_category: Optional[str] = None,
    priority: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    total_count = ticket_manager.count(
        source=source,
        status=status,
        status_category=status_category,
        priority=priority,
    )
    tickets = ticket_manager.list(
        source=source,
        status=status,
        status_category=status_category,
        priority=priority,
        limit=limit,
        offset=offset,
    )
    return {
        "tickets": [format_unified_ticket_summary(t) for t in tickets],
        "pagination": build_pagination(total_count, limit, offset),
    }


def update_unified_ticket(
    ticket_manager: TicketManager,
    ticket_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    status_category: Optional[str] = None,
    priority: Optional[int] = None,
    labels: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    ticket = ticket_manager.update(
        ticket_id=ticket_id,
        title=title,
        description=description,
        status=status,
        status_category=status_category,
        priority=priority,
        labels=labels,
        tags=tags,
    )

    if not ticket:
        return {"error": "not_found", "message": f"Ticket not found: {ticket_id}"}

    return {
        "success": True,
        "ticket": format_unified_ticket(ticket),
    }


def link_unified_ticket_external(
    ticket_manager: TicketManager,
    ticket_id: str,
    external_item_id: str,
) -> dict:
    success = ticket_manager.link_external(ticket_id, external_item_id)
    if not success:
        return {"error": "link_failed", "message": "Could not link ticket to external item"}

    return {"success": True, "ticket_id": ticket_id, "external_item_id": external_item_id}


def update_unified_ticket_ac(
    ticket_manager: TicketManager,
    ticket_id: str,
    ac_index: int,
    status: str,
    evidence: Optional[str] = None,
) -> dict:
    success = ticket_manager.update_ac_status(ticket_id, ac_index, status, evidence)
    if not success:
        return {"error": "update_failed", "message": "Could not update AC status"}

    return {
        "success": True,
        "ticket_id": ticket_id,
        "ac_index": ac_index,
        "status": status,
    }


def add_unified_ticket_ac(
    ticket_manager: TicketManager,
    ticket_id: str,
    text: str,
) -> dict:
    index = ticket_manager.add_acceptance_criterion(ticket_id, text)
    return {
        "success": True,
        "ticket_id": ticket_id,
        "ac_index": index,
        "text": text,
    }
