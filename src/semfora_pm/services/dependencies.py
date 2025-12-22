"""Shared dependency operations for CLI and MCP."""

from __future__ import annotations

from typing import Callable, Optional

from ..dependencies import DependencyManager
from ..external_items import ExternalItemsManager
from ..output.pagination import paginate


def add_dependency(
    dep_manager: DependencyManager,
    ext_manager: ExternalItemsManager,
    source_id: str,
    target_id: str,
    relation: str = "blocks",
    source_type: str = "local",
    target_type: str = "local",
    notes: Optional[str] = None,
    cache_external: Optional[Callable[[str], Optional[str]]] = None,
) -> dict:
    if source_type == "external":
        uuid = ext_manager.get_uuid_for_provider_id(source_id)
        if not uuid and cache_external:
            uuid = cache_external(source_id)
        if uuid:
            source_id = uuid

    if target_type == "external":
        uuid = ext_manager.get_uuid_for_provider_id(target_id)
        if not uuid and cache_external:
            uuid = cache_external(target_id)
        if uuid:
            target_id = uuid

    dep = dep_manager.add(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
        notes=notes,
    )

    return {
        "success": True,
        "dependency": {
            "id": dep.id,
            "source_id": dep.source_id,
            "source_type": dep.source_type,
            "target_id": dep.target_id,
            "target_type": dep.target_type,
            "relation": dep.relation,
            "notes": dep.notes,
        },
    }


def remove_dependency(
    dep_manager: DependencyManager,
    source_id: str,
    target_id: str,
    relation: Optional[str] = None,
    source_type: str = "local",
    target_type: str = "local",
) -> dict:
    count = dep_manager.remove(
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        source_type=source_type,
        target_type=target_type,
    )
    return {"success": True, "removed_count": count}


def get_blockers(
    dep_manager: DependencyManager,
    item_id: str,
    item_type: str = "local",
    recursive: bool = False,
    include_resolved: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    blockers = dep_manager.get_blockers(
        item_id=item_id,
        item_type=item_type,
        recursive=recursive,
        include_resolved=include_resolved,
    )

    formatted = [
        {
            "item_type": b.item_type,
            "item_id": b.item_id,
            "title": b.title,
            "status": b.status,
            "depth": b.depth,
            "resolved": b.resolved,
        }
        for b in blockers
    ]
    page, pagination = paginate(formatted, limit, offset)

    unresolved_count = len([b for b in blockers if not b.resolved])
    return {
        "blockers": page,
        "pagination": pagination,
        "count": len(formatted),
        "unresolved_count": unresolved_count,
        "is_blocked": unresolved_count > 0,
    }


def get_ready_work(
    dep_manager: DependencyManager,
    include_local: bool = True,
    limit: int = 5,
    offset: int = 0,
) -> dict:
    ready = dep_manager.get_ready_work(
        include_local=include_local,
        limit=limit + offset,
    )
    formatted = [
        {
            "item_type": r.item_type,
            "item_id": r.item_id,
            "title": r.title,
            "status": r.status,
            "priority": r.priority,
            "linked_ticket_id": r.linked_ticket_id,
            "linked_epic_id": r.linked_epic_id,
        }
        for r in ready
    ]
    page, pagination = paginate(formatted, limit, offset)
    return {"ready_items": page, "pagination": pagination, "count": len(formatted)}
