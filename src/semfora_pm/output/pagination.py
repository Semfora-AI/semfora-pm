"""Pagination helpers for list responses."""

from __future__ import annotations

from typing import Any, Iterable, Sequence


def build_pagination(total_count: int, limit: int, offset: int) -> dict:
    """Build pagination metadata."""
    has_more = offset + limit < total_count
    next_offset = offset + limit if has_more else None
    return {
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset,
    }


def paginate(items: Sequence[Any], limit: int, offset: int) -> tuple[list[Any], dict]:
    """Slice items and return pagination metadata."""
    total_count = len(items)
    page = list(items[offset:offset + limit])
    return page, build_pagination(total_count, limit, offset)
