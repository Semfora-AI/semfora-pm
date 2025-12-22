"""Shared Linear project operations for CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import get_client_for_path
from ..linear_client import LinearConfig
from ..output.pagination import paginate


def list_projects(path: Optional[Path] = None, limit: int = 50, offset: int = 0) -> dict:
    client, _ = get_client_for_path(path)
    projects = client.get_projects()
    summaries = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "state": p.get("state"),
            "teams": [t.get("name") for t in p.get("teams", {}).get("nodes", [])],
            "url": p.get("url"),
        }
        for p in projects
    ]
    page, pagination = paginate(summaries, limit, offset)
    return {"projects": page, "pagination": pagination}


def list_labels(path: Optional[Path] = None, limit: int = 200, offset: int = 0) -> dict:
    client, _ = get_client_for_path(path)
    labels = client.get_labels()
    valid_labels = [l for l in labels if "," not in l["name"]]
    summaries = [
        {
            "id": l.get("id"),
            "name": l.get("name"),
            "color": l.get("color"),
        }
        for l in sorted(valid_labels, key=lambda l: l["name"].lower())
    ]
    page, pagination = paginate(summaries, limit, offset)
    return {"labels": page, "pagination": pagination}


def create_project(
    name: str,
    description: Optional[str] = None,
    path: Optional[Path] = None,
) -> dict:
    client, _ = get_client_for_path(path)
    config = LinearConfig.load()
    if not config or not config.team_id:
        return {"error": "No default team configured. Run 'semfora-pm auth setup'."}

    project = client.create_project(
        name=name,
        team_ids=[config.team_id],
        description=description,
    )
    return {"project": project}


def add_tickets_to_project(
    project_name: str,
    tickets: list[str],
    path: Optional[Path] = None,
) -> dict:
    client, _ = get_client_for_path(path)
    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)
    if not project:
        return {"error": f"Project '{project_name}' not found"}

    results = []
    for tid in tickets:
        issue_id = client.get_issue_id_by_identifier(tid)
        if not issue_id:
            results.append({"identifier": tid, "status": "not_found"})
            continue
        try:
            client.add_issue_to_project(issue_id, project["id"])
            results.append({"identifier": tid, "status": "added"})
        except Exception as exc:
            results.append({"identifier": tid, "status": "error", "error": str(exc)})

    return {
        "project": {"id": project["id"], "name": project["name"], "url": project.get("url")},
        "results": results,
        "added": sum(1 for r in results if r["status"] == "added"),
    }


def describe_project(
    project_name: str,
    description: str,
    path: Optional[Path] = None,
) -> dict:
    client, _ = get_client_for_path(path)
    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)
    if not project:
        return {"error": f"Project '{project_name}' not found"}

    client.update_project(project["id"], description=description)
    return {"project": {"id": project["id"], "name": project["name"]}, "updated": True}


def show_project(
    project_name: str,
    limit: int = 50,
    offset: int = 0,
    path: Optional[Path] = None,
) -> dict:
    client, _ = get_client_for_path(path)
    projects = client.get_projects()
    project = next((p for p in projects if p["name"].lower() == project_name.lower()), None)
    if not project:
        return {"error": f"Project '{project_name}' not found"}

    details = client.get_project_details(project["id"])
    if not details:
        return {"error": "Could not fetch project details"}

    issues = details.get("issues", {}).get("nodes", [])
    issue_summaries = [
        {
            "identifier": i.get("identifier"),
            "title": i.get("title"),
            "state": i.get("state", {}).get("name"),
            "priority": i.get("priority"),
        }
        for i in issues
    ]
    page, pagination = paginate(issue_summaries, limit, offset)

    return {
        "project": {
            "id": details.get("id"),
            "name": details.get("name"),
            "state": details.get("state"),
            "url": details.get("url"),
            "target_date": details.get("targetDate"),
            "description": details.get("description"),
        },
        "issues": page,
        "pagination": pagination,
    }
