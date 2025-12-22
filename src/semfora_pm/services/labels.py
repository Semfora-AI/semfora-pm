"""Shared label operations for CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import get_client_for_path


LABEL_COLOR_SCHEME = {
    "engine": "#E07C24",
    "adk": "#8B5CF6",
    "cli": "#10B981",
    "pm": "#EC4899",
    "docs": "#6B7280",
    "infra": "#64748B",
    "high-priority": "#EF4444",
    "north-star": "#F59E0B",
    "blocker": "#DC2626",
    "quick-win": "#22C55E",
    "performance": "#0EA5E9",
    "testing": "#14B8A6",
    "validation": "#06B6D4",
    "improvement": "#3B82F6",
    "code-quality": "#6366F1",
    "indexing": "#A855F7",
    "git": "#F97316",
    "mcp": "#84CC16",
    "monorepo": "#78716C",
    "models": "#D946EF",
    "config": "#94A3B8",
    "persistence": "#7C3AED",
    "streaming": "#2DD4BF",
    "caching": "#60A5FA",
    "cost": "#FBBF24",
    "offline": "#4ADE80",
    "ui": "#FB7185",
    "ux": "#F472B6",
    "edits": "#818CF8",
    "navigation": "#34D399",
    "visualization": "#A78BFA",
    "settings": "#9CA3AF",
    "error-handling": "#FB923C",
    "planned": "#A3E635",
    "phase-1": "#22D3EE",
    "phase-2": "#38BDF8",
    "phase-4": "#818CF8",
    "phase-5": "#C084FC",
    "ongoing": "#FCD34D",
    "core": "#EF4444",
    "distribution": "#F59E0B",
    "prompt-architecture": "#8B5CF6",
    "context": "#0891B2",
    "memory": "#7C3AED",
    "orchestration": "#6D28D9",
    "verification": "#059669",
    "confidence": "#0D9488",
    "types": "#4F46E5",
}


def list_labels(path: Optional[Path] = None) -> dict:
    client, _ = get_client_for_path(path)
    labels = client.get_labels()
    valid_labels = [l for l in labels if "," not in l["name"]]
    return {
        "labels": [
            {"id": l.get("id"), "name": l.get("name"), "color": l.get("color")}
            for l in sorted(valid_labels, key=lambda l: l["name"].lower())
        ],
        "invalid": [l.get("name") for l in labels if "," in l["name"]],
    }


def audit_labels(
    apply: bool = False,
    show_invalid: bool = False,
    path: Optional[Path] = None,
) -> dict:
    client, _ = get_client_for_path(path)
    labels = client.get_labels()

    valid_labels = []
    invalid_labels = []
    for label in labels:
        if "," in label["name"]:
            invalid_labels.append(label)
        else:
            valid_labels.append(label)

    changes = []
    for label in sorted(valid_labels, key=lambda l: l["name"].lower()):
        name = label["name"].lower()
        current_color = label.get("color", "#6B7280")
        new_color = None
        for key, color in LABEL_COLOR_SCHEME.items():
            if name == key or name.startswith(key) or key in name:
                new_color = color
                break
        if new_color is None:
            new_color = "#6B7280"
        if current_color.lower() != new_color.lower():
            changes.append({"id": label["id"], "name": label["name"], "color": new_color})

    updated = []
    if apply:
        for change in changes:
            if client.update_label(change["id"], color=change["color"]):
                updated.append(change["name"])

    return {
        "valid_count": len(valid_labels),
        "invalid_count": len(invalid_labels),
        "invalid_labels": [l["name"] for l in invalid_labels] if show_invalid else [],
        "changes": changes,
        "updated": updated,
    }
