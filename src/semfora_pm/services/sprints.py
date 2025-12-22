"""Shared sprint operations for CLI and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import get_client_for_path
from ..pm_config import resolve_context, scan_pm_directories
from ..output.pagination import paginate


def sprint_status(
    path: Optional[Path] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    issues = client.get_team_issues(context.team_id)
    todo = [i for i in issues if i["state"]["name"] == "Todo"]
    in_progress = [i for i in issues if i["state"]["name"] == "In Progress"]
    in_review = [i for i in issues if i["state"]["name"] == "In Review"]

    def summarize(items: list[dict]) -> list[dict]:
        return [{"identifier": i["identifier"], "title": i["title"], "priority": i.get("priority")} for i in items]

    todo_page, todo_pagination = paginate(summarize(todo), limit, offset)
    in_progress_page, in_progress_pagination = paginate(summarize(in_progress), limit, offset)
    in_review_page, in_review_pagination = paginate(summarize(in_review), limit, offset)

    return {
        "context": {"team_id": context.team_id, "team_name": context.team_name},
        "todo": todo_page,
        "in_progress": in_progress_page,
        "in_review": in_review_page,
        "pagination": {
            "todo": todo_pagination,
            "in_progress": in_progress_pagination,
            "in_review": in_review_pagination,
        },
        "summary": {
            "todo_count": len(todo),
            "in_progress_count": len(in_progress),
            "in_review_count": len(in_review),
            "total_active": len(todo) + len(in_progress) + len(in_review),
        },
    }


def sprint_suggest(
    points: int = 20,
    label: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    path: Optional[Path] = None,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    all_issues = client.get_team_issues(context.team_id)
    backlog = [i for i in all_issues if i["state"]["name"] == "Backlog"]
    if label:
        backlog = [i for i in backlog if any(l["name"] == label for l in i.get("labels", {}).get("nodes", []))]

    sorted_issues = sorted(
        backlog,
        key=lambda i: (i.get("priority", 4), -(i.get("estimate") or 0))
    )

    suggested = []
    current_points = 0
    for issue in sorted_issues:
        if current_points >= points:
            break
        estimate = issue.get("estimate") or 2
        if current_points + estimate <= points:
            suggested.append(issue)
            current_points += estimate

    summaries = [
        {
            "identifier": i["identifier"],
            "title": i["title"],
            "priority": i.get("priority"),
            "estimate": i.get("estimate"),
            "labels": [l["name"] for l in i.get("labels", {}).get("nodes", [])],
        }
        for i in suggested
    ]
    page, pagination = paginate(summaries, limit, offset)

    return {
        "suggested": page,
        "pagination": pagination,
        "total_points": current_points,
        "target_points": points,
    }


def sprint_plan(
    name: str,
    tickets: list[str],
    dry_run: bool = False,
    path: Optional[Path] = None,
) -> dict:
    client, context = get_client_for_path(path)
    if not context.team_id:
        return {"error": "No team configured. Create .pm/config.json or run 'semfora-pm auth setup'."}

    all_issues = client.get_team_issues(context.team_id)
    issue_by_id = {i["identifier"]: i for i in all_issues}

    sprint_issues = [issue_by_id[tid] for tid in tickets if tid in issue_by_id]
    if not sprint_issues:
        return {"error": "No valid tickets found"}

    if dry_run:
        return {"sprint": name, "tickets": [i["identifier"] for i in sprint_issues], "dry_run": True}

    states = client.get_team_states(context.team_id)
    todo_state_id = states.get("Todo")
    if not todo_state_id:
        return {"error": "'Todo' state not found"}

    moved = []
    failed = []
    for issue in sprint_issues:
        try:
            client.update_issue(issue["id"], state_id=todo_state_id)
            moved.append(issue["identifier"])
        except Exception as exc:
            failed.append({"identifier": issue["identifier"], "error": str(exc)})

    return {
        "sprint": name,
        "moved": moved,
        "failed": failed,
        "moved_count": len(moved),
    }


def sprint_status_aggregated(
    base_path: Optional[Path] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    target_path = base_path or Path.cwd()
    dirs = scan_pm_directories(target_path, max_depth=3)

    if not dirs:
        context = resolve_context(target_path)
        if context.has_team():
            return sprint_status(target_path, limit=limit, offset=offset)
        return {"error": "No .pm/ configurations found. Run 'semfora-pm init' to create one."}

    seen_configs: set[tuple] = set()
    all_issues: dict[str, dict] = {}
    projects_info: list[dict] = []
    errors: list[dict] = []

    for dir_info in dirs:
        config_key = (dir_info.team_id, dir_info.team_name, dir_info.project_id, dir_info.project_name)
        if config_key in seen_configs:
            continue
        seen_configs.add(config_key)

        try:
            client, context = get_client_for_path(dir_info.path)
            team_id = context.team_id
            if not team_id and context.team_name:
                team_id = client.get_team_id_by_name(context.team_name)
            if not team_id:
                continue

            issues = client.get_team_issues(team_id)
            projects_info.append({
                "path": str(dir_info.path),
                "project": context.project_name or context.team_name or "Unknown",
                "count": len(issues),
            })
            for issue in issues:
                all_issues.setdefault(issue["identifier"], issue)
        except Exception as exc:
            errors.append({"path": str(dir_info.path), "error": str(exc)})

    issues_list = list(all_issues.values())
    todo = [i for i in issues_list if i["state"]["name"] == "Todo"]
    in_progress = [i for i in issues_list if i["state"]["name"] == "In Progress"]
    in_review = [i for i in issues_list if i["state"]["name"] == "In Review"]

    def summarize(items: list[dict]) -> list[dict]:
        return [{"identifier": i["identifier"], "title": i["title"], "priority": i.get("priority")} for i in items]

    todo_page, todo_pagination = paginate(summarize(todo), limit, offset)
    in_progress_page, in_progress_pagination = paginate(summarize(in_progress), limit, offset)
    in_review_page, in_review_pagination = paginate(summarize(in_review), limit, offset)

    return {
        "aggregated": True,
        "projects": projects_info,
        "todo": todo_page,
        "in_progress": in_progress_page,
        "in_review": in_review_page,
        "pagination": {
            "todo": todo_pagination,
            "in_progress": in_progress_pagination,
            "in_review": in_review_pagination,
        },
        "summary": {
            "todo_count": len(todo),
            "in_progress_count": len(in_progress),
            "in_review_count": len(in_review),
            "total_active": len(todo) + len(in_progress) + len(in_review),
            "projects_count": len(projects_info),
            "unique_tickets": len(all_issues),
        },
        "errors": errors if errors else None,
    }
