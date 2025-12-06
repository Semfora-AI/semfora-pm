"""Linear API client for Semfora PM."""

import os
import json
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from pathlib import Path
import urllib.request
import urllib.error

if TYPE_CHECKING:
    from .pm_config import PMContext

LINEAR_API_URL = "https://api.linear.app/graphql"
CONFIG_DIR = Path.home() / ".config" / "semfora-pm"
CONFIG_FILE = CONFIG_DIR / "config.json"


class AuthenticationError(Exception):
    """Raised when Linear authentication fails or is not configured."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = suggestions or []


@dataclass
class LinearConfig:
    """Linear API configuration."""
    api_key: str
    team_id: Optional[str] = None
    project_id: Optional[str] = None

    def save(self) -> None:
        """Save config to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "api_key": self.api_key,
                "team_id": self.team_id,
                "project_id": self.project_id,
            }, f, indent=2)
        # Secure the file
        os.chmod(CONFIG_FILE, 0o600)

    @classmethod
    def load(cls) -> Optional["LinearConfig"]:
        """Load config from file or environment."""
        # Try environment variable first
        api_key = os.environ.get("LINEAR_API_KEY")
        if api_key:
            # Also try to get team_id from config file even if using env key
            team_id = None
            project_id = None
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE) as f:
                        data = json.load(f)
                    team_id = data.get("team_id")
                    project_id = data.get("project_id")
                except Exception:
                    pass
            return cls(api_key=api_key, team_id=team_id, project_id=project_id)

        # Try config file
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            return cls(
                api_key=data["api_key"],
                team_id=data.get("team_id"),
                project_id=data.get("project_id"),
            )

        return None

    @classmethod
    def from_context(cls, context: "PMContext") -> Optional["LinearConfig"]:
        """Create LinearConfig from a PMContext."""
        if not context.api_key:
            return None
        return cls(
            api_key=context.api_key,
            team_id=context.team_id,
            project_id=context.project_id,
        )

    @classmethod
    def get_auth_help_message(cls) -> str:
        """Get helpful message about authentication options."""
        return """Linear authentication not configured.

To authenticate, use one of these methods:

1. Environment variable:
   $ export LINEAR_API_KEY=lin_api_xxxxxxxxxxxx

2. Run auth setup:
   $ semfora-pm auth setup

3. Create .pm/config.yaml in your project:
   provider: linear
   linear:
     team_name: "Your Team"

   And set LINEAR_API_KEY environment variable.

To get an API key:
   https://linear.app/settings/api
"""


class LinearClient:
    """Client for Linear GraphQL API."""

    def __init__(self, config: LinearConfig):
        self.config = config
        self._label_cache: dict[str, str] = {}  # name -> id
        self._team_cache: dict[str, dict] = {}  # id -> team data
        self._team_name_cache: dict[str, str] = {}  # name.lower() -> id
        self._state_cache: dict[str, dict] = {}  # team_id -> {name: id}
        self._project_cache: dict[str, dict] = {}  # id -> project data
        self._project_name_cache: dict[str, str] = {}  # name.lower() -> id

    @classmethod
    def from_context(cls, path_or_context: "PMContext | Path | None" = None) -> "LinearClient":
        """Create a LinearClient from a PMContext or path, resolving names to IDs.

        Args:
            path_or_context: Either a PMContext, a Path to resolve context from,
                           or None to use current directory.
        """
        from .pm_config import resolve_context, PMContext

        # Resolve to PMContext if needed
        if path_or_context is None:
            context = resolve_context()
        elif isinstance(path_or_context, PMContext):
            context = path_or_context
        else:
            # It's a Path
            context = resolve_context(path_or_context)

        if not context.api_key:
            raise AuthenticationError(
                "Linear API key not configured.",
                suggestions=[
                    "Set: export LINEAR_API_KEY=lin_api_xxx",
                    "Or run: semfora-pm auth setup",
                ],
            )

        config = LinearConfig(
            api_key=context.api_key,
            team_id=context.team_id,
            project_id=context.project_id,
        )

        client = cls(config)

        # Resolve team name to ID if needed
        if not config.team_id and context.team_name:
            team_id = client.get_team_id_by_name(context.team_name)
            if team_id:
                client.config.team_id = team_id
            else:
                raise ValueError(f"Team not found: {context.team_name}")

        # Resolve project name to ID if needed
        if not config.project_id and context.project_name:
            project_id = client.get_project_id_by_name(
                context.project_name,
                team_id=client.config.team_id,
            )
            if project_id:
                client.config.project_id = project_id
            # Don't error if project not found - it's optional

        return client

    def get_team_id_by_name(self, name: str) -> Optional[str]:
        """Get team ID by name (case-insensitive)."""
        name_lower = name.lower()

        # Check cache
        if name_lower in self._team_name_cache:
            return self._team_name_cache[name_lower]

        # Fetch teams and build cache
        teams = self.get_teams()
        for team in teams:
            self._team_name_cache[team["name"].lower()] = team["id"]

        return self._team_name_cache.get(name_lower)

    def get_project_id_by_name(
        self,
        name: str,
        team_id: Optional[str] = None,
    ) -> Optional[str]:
        """Get project ID by name (case-insensitive)."""
        name_lower = name.lower()

        # Fetch projects and search
        projects = self.get_projects(team_id)
        for project in projects:
            if project["name"].lower() == name_lower:
                return project["id"]

        return None

    def _request(self, query: str, variables: Optional[dict] = None) -> dict:
        """Make GraphQL request to Linear API."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            LINEAR_API_URL,
            data=data,
            headers={
                "Authorization": self.config.api_key,
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                if "errors" in result:
                    raise Exception(f"GraphQL errors: {result['errors']}")
                return result["data"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise Exception(f"Linear API error ({e.code}): {error_body}")

    def get_teams(self) -> list[dict]:
        """Get all teams."""
        query = """
        query {
            teams {
                nodes {
                    id
                    name
                    key
                }
            }
        }
        """
        result = self._request(query)
        teams = result["teams"]["nodes"]
        for team in teams:
            self._team_cache[team["id"]] = team
        return teams

    def get_team_states(self, team_id: str) -> dict[str, str]:
        """Get workflow states for a team. Returns {name: id}."""
        if team_id in self._state_cache:
            return self._state_cache[team_id]

        query = """
        query($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                        type
                    }
                }
            }
        }
        """
        result = self._request(query, {"teamId": team_id})
        states = {s["name"]: s["id"] for s in result["team"]["states"]["nodes"]}
        self._state_cache[team_id] = states
        return states

    def get_projects(self, team_id: Optional[str] = None) -> list[dict]:
        """Get all projects, optionally filtered by team."""
        query = """
        query {
            projects {
                nodes {
                    id
                    name
                    slugId
                    state
                    teams {
                        nodes {
                            id
                            name
                        }
                    }
                }
            }
        }
        """
        result = self._request(query)
        projects = result["projects"]["nodes"]

        if team_id:
            projects = [
                p for p in projects
                if any(t["id"] == team_id for t in p["teams"]["nodes"])
            ]

        return projects

    def get_labels(self, team_id: Optional[str] = None) -> list[dict]:
        """Get all labels with pagination to ensure we fetch all labels."""
        all_labels = []
        cursor = None

        while True:
            query = """
            query($first: Int!, $after: String) {
                issueLabels(first: $first, after: $after) {
                    nodes {
                        id
                        name
                        color
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
            """
            result = self._request(query, {"first": 100, "after": cursor})
            labels = result["issueLabels"]["nodes"]
            all_labels.extend(labels)

            page_info = result["issueLabels"]["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

        for label in all_labels:
            self._label_cache[label["name"].lower()] = label["id"]
        return all_labels

    def get_team_issues(self, team_id: str, limit: int = 250) -> list[dict]:
        """Get all issues for a team."""
        query = """
        query($teamId: String!, $first: Int) {
            team(id: $teamId) {
                issues(first: $first) {
                    nodes {
                        id
                        identifier
                        title
                        description
                        url
                        priority
                        estimate
                        state {
                            id
                            name
                        }
                        labels {
                            nodes {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
        """
        result = self._request(query, {"teamId": team_id, "first": limit})
        return result["team"]["issues"]["nodes"]

    def delete_label(self, label_id: str) -> bool:
        """Delete a label by ID."""
        mutation = """
        mutation($id: String!) {
            issueLabelDelete(id: $id) {
                success
            }
        }
        """
        try:
            result = self._request(mutation, {"id": label_id})
            return result["issueLabelDelete"]["success"]
        except Exception:
            return False

    def update_label(
        self,
        label_id: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Update a label's properties (name, color, description)."""
        mutation = """
        mutation($id: String!, $input: IssueLabelUpdateInput!) {
            issueLabelUpdate(id: $id, input: $input) {
                success
                issueLabel {
                    id
                    name
                    color
                }
            }
        }
        """
        input_data: dict = {}
        if name is not None:
            input_data["name"] = name
        if color is not None:
            input_data["color"] = color
        if description is not None:
            input_data["description"] = description

        if not input_data:
            return True  # Nothing to update

        try:
            result = self._request(mutation, {"id": label_id, "input": input_data})
            return result["issueLabelUpdate"]["success"]
        except Exception:
            return False

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        state: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> bool:
        """Update a project's properties."""
        mutation = """
        mutation($id: String!, $input: ProjectUpdateInput!) {
            projectUpdate(id: $id, input: $input) {
                success
                project {
                    id
                    name
                    description
                    state
                }
            }
        }
        """
        input_data: dict = {}
        if name is not None:
            input_data["name"] = name
        if description is not None:
            input_data["description"] = description
        if state is not None:
            input_data["state"] = state
        if target_date is not None:
            input_data["targetDate"] = target_date

        if not input_data:
            return True

        try:
            result = self._request(mutation, {"id": project_id, "input": input_data})
            return result["projectUpdate"]["success"]
        except Exception as e:
            raise Exception(f"Failed to update project: {e}")

    def get_project_details(self, project_id: str) -> Optional[dict]:
        """Get detailed project information including issues."""
        query = """
        query($id: String!) {
            project(id: $id) {
                id
                name
                description
                state
                url
                targetDate
                issues {
                    nodes {
                        id
                        identifier
                        title
                        state {
                            name
                            type
                        }
                        priority
                    }
                }
                teams {
                    nodes {
                        id
                        name
                    }
                }
            }
        }
        """
        try:
            result = self._request(query, {"id": project_id})
            return result.get("project")
        except Exception:
            return None

    def batch_update_issue_state(self, issue_ids: list[str], state_id: str) -> int:
        """Update multiple issues to a new state. Returns count of successful updates."""
        success_count = 0
        for issue_id in issue_ids:
            try:
                self.update_issue(issue_id, state_id=state_id)
                success_count += 1
            except Exception:
                pass
        return success_count

    def get_or_create_label(self, name: str, team_id: str) -> str:
        """Get label ID by name, creating if it doesn't exist."""
        # Check cache first
        if name.lower() in self._label_cache:
            return self._label_cache[name.lower()]

        # Refresh cache (with pagination)
        self.get_labels()
        if name.lower() in self._label_cache:
            return self._label_cache[name.lower()]

        # Try to create label
        mutation = """
        mutation($input: IssueLabelCreateInput!) {
            issueLabelCreate(input: $input) {
                success
                issueLabel {
                    id
                    name
                }
            }
        }
        """
        try:
            result = self._request(mutation, {
                "input": {
                    "name": name,
                    "teamId": team_id,
                }
            })
            label_id = result["issueLabelCreate"]["issueLabel"]["id"]
            self._label_cache[name.lower()] = label_id
            return label_id
        except Exception as e:
            # If label already exists (duplicate), search for it by name
            if "duplicate label" in str(e).lower() or "already exists" in str(e).lower():
                # Search for the existing label directly
                search_query = """
                query($filter: IssueLabelFilter) {
                    issueLabels(filter: $filter) {
                        nodes {
                            id
                            name
                        }
                    }
                }
                """
                result = self._request(search_query, {
                    "filter": {"name": {"eq": name}}
                })
                labels = result["issueLabels"]["nodes"]
                if labels:
                    label_id = labels[0]["id"]
                    self._label_cache[name.lower()] = label_id
                    return label_id
            # Re-raise if not a duplicate error
            raise

    def create_issue(
        self,
        title: str,
        description: str,
        team_id: str,
        priority: int = 3,
        labels: Optional[list[str]] = None,
        estimate: Optional[int] = None,
        state_id: Optional[str] = None,
        project_id: Optional[str] = None,
        milestone_id: Optional[str] = None,
    ) -> dict:
        """Create a new issue.

        Args:
            title: Issue title
            description: Issue description (markdown)
            team_id: Team ID to create the issue in
            priority: Priority level (1=Urgent, 2=High, 3=Medium, 4=Low)
            labels: Optional list of label names
            estimate: Optional story point estimate
            state_id: Optional workflow state ID
            project_id: Optional project ID to add the issue to
            milestone_id: Optional milestone ID to add the issue to

        Returns:
            The created issue data
        """
        mutation = """
        mutation($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
        """

        input_data: dict = {
            "title": title,
            "description": description,
            "teamId": team_id,
            "priority": priority,
        }

        if labels:
            label_ids = [self.get_or_create_label(l, team_id) for l in labels]
            input_data["labelIds"] = label_ids

        if estimate is not None:
            input_data["estimate"] = estimate

        if state_id:
            input_data["stateId"] = state_id

        if project_id:
            input_data["projectId"] = project_id

        if milestone_id:
            input_data["projectMilestoneId"] = milestone_id

        result = self._request(mutation, {"input": input_data})
        return result["issueCreate"]["issue"]

    def update_issue(
        self,
        issue_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        labels: Optional[list[str]] = None,
        estimate: Optional[int] = None,
        state_id: Optional[str] = None,
        milestone_id: Optional[str] = None,
    ) -> dict:
        """Update an existing issue.

        Args:
            issue_id: The ID of the issue to update
            title: New title
            description: New description (markdown)
            priority: New priority level
            labels: New list of label names (replaces existing)
            estimate: New story point estimate
            state_id: New workflow state ID
            milestone_id: New milestone ID (use empty string to remove)

        Returns:
            The updated issue data
        """
        mutation = """
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
        """

        input_data: dict = {}

        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if priority is not None:
            input_data["priority"] = priority
        if estimate is not None:
            input_data["estimate"] = estimate
        if state_id is not None:
            input_data["stateId"] = state_id
        if labels is not None:
            # Need team_id to create labels - get from issue first
            label_ids = [self.get_or_create_label(l, self.config.team_id) for l in labels]
            input_data["labelIds"] = label_ids
        if milestone_id is not None:
            input_data["projectMilestoneId"] = milestone_id if milestone_id else None

        result = self._request(mutation, {"id": issue_id, "input": input_data})
        return result["issueUpdate"]["issue"]

    def search_issues(self, query: str, team_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Search for issues by title (contains match).

        Args:
            query: Search string to match in title
            team_id: Optional team ID to filter results
            limit: Maximum results to return

        Returns:
            List of matching issues with basic info
        """
        gql = """
        query($filter: IssueFilter, $first: Int) {
            issues(filter: $filter, first: $first) {
                nodes {
                    id
                    identifier
                    title
                    url
                    priority
                    estimate
                    state {
                        name
                        type
                    }
                    labels {
                        nodes {
                            name
                        }
                    }
                }
            }
        }
        """
        filter_obj: dict = {"title": {"containsIgnoreCase": query}}
        if team_id:
            filter_obj["team"] = {"id": {"eq": team_id}}

        result = self._request(gql, {"filter": filter_obj, "first": limit})
        return result["issues"]["nodes"]

    def search_issues_multi(self, queries: list[str], team_id: Optional[str] = None) -> list[dict]:
        """Search for issues matching any of multiple queries.

        Useful for duplicate detection - searches for each title and dedupes results.

        Args:
            queries: List of search strings (typically ticket titles)
            team_id: Optional team ID to filter results

        Returns:
            Deduplicated list of matching issues
        """
        seen_ids: set[str] = set()
        results: list[dict] = []

        for query in queries:
            # Extract key words (skip very short words)
            words = [w for w in query.split() if len(w) > 3]
            # Search with first few significant words
            search_term = " ".join(words[:4]) if words else query[:30]

            matches = self.search_issues(search_term, team_id, limit=20)
            for issue in matches:
                if issue["id"] not in seen_ids:
                    seen_ids.add(issue["id"])
                    results.append(issue)

        return results

    def get_issue_by_identifier(self, identifier: str) -> Optional[dict]:
        """Get issue by its identifier (e.g., 'SEM-123')."""
        query = """
        query($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                url
                priority
                estimate
                state {
                    id
                    name
                }
                labels {
                    nodes {
                        id
                        name
                    }
                }
            }
        }
        """
        try:
            result = self._request(query, {"id": identifier})
            return result.get("issue")
        except Exception:
            return None

    def get_issue_full(self, identifier: str) -> Optional[dict]:
        """Get full issue details by identifier (e.g., 'SEM-123').

        Returns all available data including assignee, project, cycle,
        relations, sub-issues, dates, and more.
        """
        query = """
        query($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                url
                priority
                estimate
                createdAt
                updatedAt
                startedAt
                completedAt
                canceledAt
                dueDate
                state {
                    id
                    name
                    type
                    color
                }
                assignee {
                    id
                    name
                    email
                    avatarUrl
                }
                creator {
                    id
                    name
                }
                labels {
                    nodes {
                        id
                        name
                        color
                    }
                }
                project {
                    id
                    name
                    state
                }
                cycle {
                    id
                    name
                    number
                    startsAt
                    endsAt
                }
                parent {
                    id
                    identifier
                    title
                }
                children {
                    nodes {
                        id
                        identifier
                        title
                        state {
                            name
                        }
                    }
                }
                relations {
                    nodes {
                        id
                        type
                        relatedIssue {
                            id
                            identifier
                            title
                        }
                    }
                }
                comments {
                    nodes {
                        id
                        body
                        createdAt
                        user {
                            name
                        }
                    }
                }
                attachments {
                    nodes {
                        id
                        title
                        url
                    }
                }
            }
        }
        """
        try:
            result = self._request(query, {"id": identifier})
            return result.get("issue")
        except Exception:
            return None

    def create_project(
        self,
        name: str,
        team_ids: list[str],
        description: Optional[str] = None,
    ) -> dict:
        """Create a new project."""
        mutation = """
        mutation($input: ProjectCreateInput!) {
            projectCreate(input: $input) {
                success
                project {
                    id
                    name
                    slugId
                    url
                }
            }
        }
        """
        input_data = {
            "name": name,
            "teamIds": team_ids,
        }
        if description:
            input_data["description"] = description

        result = self._request(mutation, {"input": input_data})
        return result["projectCreate"]["project"]

    def add_issue_to_project(self, issue_id: str, project_id: str) -> bool:
        """Add an issue to a project."""
        mutation = """
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
            }
        }
        """
        result = self._request(mutation, {
            "id": issue_id,
            "input": {"projectId": project_id}
        })
        return result["issueUpdate"]["success"]

    def create_issue_relation(
        self,
        issue_id: str,
        related_issue_id: str,
        relation_type: str = "blocks",  # blocks, duplicate, related
    ) -> dict:
        """Create a relation between two issues."""
        mutation = """
        mutation($input: IssueRelationCreateInput!) {
            issueRelationCreate(input: $input) {
                success
                issueRelation {
                    id
                    type
                }
            }
        }
        """
        result = self._request(mutation, {
            "input": {
                "issueId": issue_id,
                "relatedIssueId": related_issue_id,
                "type": relation_type,
            }
        })
        return result["issueRelationCreate"]

    def get_issue_id_by_identifier(self, identifier: str) -> Optional[str]:
        """Get issue ID from identifier (e.g., 'SEM-5' -> actual ID)."""
        query = """
        query($filter: IssueFilter) {
            issues(filter: $filter) {
                nodes {
                    id
                    identifier
                }
            }
        }
        """
        # Extract the number from identifier
        result = self._request(query, {
            "filter": {
                "number": {"eq": int(identifier.split("-")[1])}
            }
        })
        issues = result["issues"]["nodes"]
        for issue in issues:
            if issue["identifier"] == identifier:
                return issue["id"]
        return None

    # ============ Milestone Methods ============

    def get_project_milestones(self, project_id: str) -> list[dict]:
        """Get all milestones for a project."""
        query = """
        query($projectId: String!) {
            project(id: $projectId) {
                projectMilestones {
                    nodes {
                        id
                        name
                        description
                        sortOrder
                        targetDate
                    }
                }
            }
        }
        """
        result = self._request(query, {"projectId": project_id})
        project = result.get("project")
        if project and project.get("projectMilestones"):
            return project["projectMilestones"]["nodes"]
        return []

    def create_milestone(
        self,
        project_id: str,
        name: str,
        description: Optional[str] = None,
        target_date: Optional[str] = None,
        sort_order: Optional[float] = None,
    ) -> dict:
        """Create a new milestone for a project.

        Args:
            project_id: The ID of the project
            name: Name of the milestone
            description: Optional markdown description
            target_date: Optional target date (ISO 8601 format, e.g., '2024-12-31')
            sort_order: Optional sort order (float)

        Returns:
            The created milestone data
        """
        mutation = """
        mutation($input: ProjectMilestoneCreateInput!) {
            projectMilestoneCreate(input: $input) {
                success
                projectMilestone {
                    id
                    name
                    description
                    sortOrder
                    targetDate
                }
            }
        }
        """
        input_data: dict = {
            "projectId": project_id,
            "name": name,
        }
        if description is not None:
            input_data["description"] = description
        if target_date is not None:
            input_data["targetDate"] = target_date
        if sort_order is not None:
            input_data["sortOrder"] = sort_order

        result = self._request(mutation, {"input": input_data})
        return result["projectMilestoneCreate"]["projectMilestone"]

    def update_milestone(
        self,
        milestone_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        target_date: Optional[str] = None,
        sort_order: Optional[float] = None,
    ) -> bool:
        """Update an existing milestone.

        Args:
            milestone_id: The ID of the milestone to update
            name: New name for the milestone
            description: New markdown description
            target_date: New target date (ISO 8601 format)
            sort_order: New sort order

        Returns:
            True if successful
        """
        mutation = """
        mutation($id: String!, $input: ProjectMilestoneUpdateInput!) {
            projectMilestoneUpdate(id: $id, input: $input) {
                success
                projectMilestone {
                    id
                    name
                    description
                    sortOrder
                    targetDate
                }
            }
        }
        """
        input_data: dict = {}
        if name is not None:
            input_data["name"] = name
        if description is not None:
            input_data["description"] = description
        if target_date is not None:
            input_data["targetDate"] = target_date
        if sort_order is not None:
            input_data["sortOrder"] = sort_order

        if not input_data:
            return True  # Nothing to update

        result = self._request(mutation, {"id": milestone_id, "input": input_data})
        return result["projectMilestoneUpdate"]["success"]

    def delete_milestone(self, milestone_id: str) -> bool:
        """Delete a milestone.

        Args:
            milestone_id: The ID of the milestone to delete

        Returns:
            True if successful
        """
        mutation = """
        mutation($id: String!) {
            projectMilestoneDelete(id: $id) {
                success
            }
        }
        """
        try:
            result = self._request(mutation, {"id": milestone_id})
            return result["projectMilestoneDelete"]["success"]
        except Exception:
            return False

    def add_issue_to_milestone(self, issue_id: str, milestone_id: str) -> bool:
        """Add an issue to a milestone.

        Args:
            issue_id: The ID of the issue
            milestone_id: The ID of the milestone

        Returns:
            True if successful
        """
        mutation = """
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
            }
        }
        """
        result = self._request(mutation, {
            "id": issue_id,
            "input": {"projectMilestoneId": milestone_id}
        })
        return result["issueUpdate"]["success"]

    def remove_issue_from_milestone(self, issue_id: str) -> bool:
        """Remove an issue from its milestone.

        Args:
            issue_id: The ID of the issue

        Returns:
            True if successful
        """
        mutation = """
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
            }
        }
        """
        result = self._request(mutation, {
            "id": issue_id,
            "input": {"projectMilestoneId": None}
        })
        return result["issueUpdate"]["success"]
