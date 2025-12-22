"""Project management configuration with directory-based detection.

This module implements the .pm/ folder specification for per-project
and per-directory PM configuration, supporting multi-org workspaces.

## .pm/ Folder Specification

The .pm/ folder contains project management configuration:

```
.pm/
└── config.json          # Main config file
```

### config.json Structure

```json
{
  "provider": "linear",
  "linear": {
    "team_id": "abc123",
    "team_name": "Semfora",
    "project_id": "xyz789",
    "project_name": "Engine"
  },
  "auth": {
    "api_key_env": "LINEAR_API_KEY_WORK"
  }
}
```

### Resolution Order

1. Check for .pm/config.json in current directory
2. Walk up parent directories looking for .pm/config.json
3. Fall back to ~/.config/semfora-pm/config.json (user default)
"""

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_cache_dir

# User-level config location
USER_CONFIG_DIR = Path.home() / ".config" / "semfora-pm"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.json"

# Directory-level config
PM_CONFIG_DIR = ".pm"
PM_CONFIG_FILE = "config.json"


@dataclass
class PMContext:
    """Resolved PM context for a directory."""

    # Source of config
    config_path: Optional[Path] = None  # Path to .pm/config.json or user config
    config_source: str = "none"  # "directory", "parent", "user", "none"

    # Provider
    provider: str = "linear"

    # Linear-specific
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None

    # Auth
    api_key: Optional[str] = None
    api_key_env: str = "LINEAR_API_KEY"

    # Local storage settings
    cache_dir: Optional[str] = None  # Override database location
    auto_link_tickets: bool = True  # Auto-cache ticket when linking plans

    def has_team(self) -> bool:
        """Check if team is configured (ID or name)."""
        return bool(self.team_id or self.team_name)

    def has_project(self) -> bool:
        """Check if project is configured (ID or name)."""
        return bool(self.project_id or self.project_name)

    def get_db_path(self) -> Path:
        """Get the database path for this context.

        Resolution order:
        1. Custom cache_dir from config (if set)
        2. Same directory as .pm/config.json (default)
        3. User cache directory fallback

        Returns:
            Path to the SQLite database file
        """
        if self.cache_dir:
            return Path(self.cache_dir) / "cache.db"

        if self.config_path:
            # Store next to config.json: .pm/cache.db
            return self.config_path.parent / "cache.db"

        # Fallback to user cache
        return Path(user_cache_dir("semfora-pm", "Semfora")) / "default.db"


@dataclass
class PMDirectoryInfo:
    """Information about a discovered PM-configured directory."""

    path: Path
    config_path: Path
    provider: str
    team_id: Optional[str]
    team_name: Optional[str]
    project_id: Optional[str]
    project_name: Optional[str]


def find_pm_config(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find the nearest .pm/config.json by walking up the directory tree.

    Args:
        start_path: Directory to start searching from (default: cwd)

    Returns:
        Path to config.json if found, None otherwise
    """
    if start_path is None:
        start_path = Path.cwd()

    start_path = Path(start_path).resolve()
    current = start_path

    while current != current.parent:
        config_path = current / PM_CONFIG_DIR / PM_CONFIG_FILE
        if config_path.exists():
            return config_path
        current = current.parent

    # Check root
    config_path = current / PM_CONFIG_DIR / PM_CONFIG_FILE
    if config_path.exists():
        return config_path

    return None


def load_pm_config(config_path: Path) -> dict:
    """Load and parse a .pm/config.json file."""
    with open(config_path) as f:
        return json.load(f) or {}


def load_user_config() -> Optional[dict]:
    """Load user-level config from ~/.config/semfora-pm/config.json."""
    if USER_CONFIG_FILE.exists():
        with open(USER_CONFIG_FILE) as f:
            return json.load(f)
    return None


def resolve_context(path: Optional[Path] = None) -> PMContext:
    """Resolve PM context for a path.

    Resolution order:
    1. .pm/config.json in the path or its parents
    2. ~/.config/semfora-pm/config.json (user default)
    3. Environment variables only

    Args:
        path: Directory to resolve context for (default: cwd)

    Returns:
        PMContext with resolved configuration
    """
    context = PMContext()

    # Step 1: Look for .pm/config.json
    pm_config_path = find_pm_config(path)

    if pm_config_path:
        data = load_pm_config(pm_config_path)
        context.config_path = pm_config_path

        # Determine if it's in the target directory or a parent
        target_dir = Path(path).resolve() if path else Path.cwd().resolve()
        config_dir = pm_config_path.parent.parent  # .pm/config.json -> .pm -> parent

        if config_dir == target_dir:
            context.config_source = "directory"
        else:
            context.config_source = "parent"

        context.provider = data.get("provider", "linear")

        # Load Linear config
        linear_config = data.get("linear", {})
        context.team_id = linear_config.get("team_id")
        context.team_name = linear_config.get("team_name")
        context.project_id = linear_config.get("project_id")
        context.project_name = linear_config.get("project_name")

        # Auth config
        auth_config = data.get("auth", {})
        context.api_key_env = auth_config.get("api_key_env", "LINEAR_API_KEY")

        # Local storage config
        local_config = data.get("local", {})
        context.cache_dir = local_config.get("cache_dir")

        # Plans config
        plans_config = data.get("plans", {})
        context.auto_link_tickets = plans_config.get("auto_link_tickets", True)

    # Step 2: Fall back to user config if no team found
    if not context.has_team():
        user_config = load_user_config()
        if user_config:
            if not context.config_path:
                context.config_path = USER_CONFIG_FILE
                context.config_source = "user"

            # Only use user config values if not already set
            if not context.team_id:
                context.team_id = user_config.get("team_id")
            if not context.project_id and not context.project_name:
                context.project_id = user_config.get("project_id")

    # Step 3: Resolve API key
    context.api_key = os.environ.get(context.api_key_env)
    if not context.api_key:
        # Try default env var
        context.api_key = os.environ.get("LINEAR_API_KEY")
    if not context.api_key:
        # Try user config
        user_config = load_user_config()
        if user_config:
            context.api_key = user_config.get("api_key")

    return context


def scan_pm_directories(
    base_path: Optional[Path] = None,
    max_depth: int = 3,
) -> list[PMDirectoryInfo]:
    """Scan directory tree for .pm/ configurations.

    Args:
        base_path: Directory to scan (default: cwd)
        max_depth: Maximum depth to search

    Returns:
        List of PMDirectoryInfo for each discovered .pm/ config
    """
    if base_path is None:
        base_path = Path.cwd()

    base_path = Path(base_path).resolve()
    results = []

    def scan(path: Path, depth: int):
        if depth > max_depth:
            return

        # Check for .pm/config.json
        config_path = path / PM_CONFIG_DIR / PM_CONFIG_FILE
        if config_path.exists():
            try:
                data = load_pm_config(config_path)
                linear_config = data.get("linear", {})

                results.append(PMDirectoryInfo(
                    path=path,
                    config_path=config_path,
                    provider=data.get("provider", "linear"),
                    team_id=linear_config.get("team_id"),
                    team_name=linear_config.get("team_name"),
                    project_id=linear_config.get("project_id"),
                    project_name=linear_config.get("project_name"),
                ))
            except Exception:
                pass

        # Scan subdirectories
        try:
            for child in path.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    scan(child, depth + 1)
        except PermissionError:
            pass

    scan(base_path, 0)
    return results


def create_pm_config(
    path: Path,
    provider: str = "linear",
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    api_key_env: Optional[str] = None,
) -> Path:
    """Create a .pm/config.json file in the specified directory.

    Args:
        path: Directory to create .pm/ in
        provider: PM provider (default: "linear")
        team_id: Linear team ID
        team_name: Linear team name (alternative to ID)
        project_id: Linear project ID
        project_name: Linear project name (alternative to ID)
        api_key_env: Custom env var for API key

    Returns:
        Path to created config file
    """
    pm_dir = Path(path) / PM_CONFIG_DIR
    pm_dir.mkdir(exist_ok=True)

    config = {
        "provider": provider,
        "linear": {},
    }

    if team_id:
        config["linear"]["team_id"] = team_id
    if team_name:
        config["linear"]["team_name"] = team_name
    if project_id:
        config["linear"]["project_id"] = project_id
    if project_name:
        config["linear"]["project_name"] = project_name

    if api_key_env:
        config["auth"] = {"api_key_env": api_key_env}

    config_path = pm_dir / PM_CONFIG_FILE
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return config_path


def get_context_help_message(context: PMContext) -> str:
    """Generate a helpful message about the current context."""
    if context.config_source == "none":
        return """No PM configuration found.

To configure PM for this directory, create .pm/config.json:

```json
{
  "provider": "linear",
  "linear": {
    "team_name": "Your Team Name",
    "project_name": "Your Project"
  }
}
```

Or run: semfora-pm init
"""

    lines = [f"PM Context (from {context.config_source}):"]
    lines.append(f"  Config: {context.config_path}")
    lines.append(f"  Provider: {context.provider}")

    if context.team_id:
        lines.append(f"  Team ID: {context.team_id}")
    elif context.team_name:
        lines.append(f"  Team: {context.team_name}")
    else:
        lines.append("  Team: Not configured")

    if context.project_id:
        lines.append(f"  Project ID: {context.project_id}")
    elif context.project_name:
        lines.append(f"  Project: {context.project_name}")

    if context.api_key:
        lines.append(f"  Auth: {context.api_key_env} (configured)")
    else:
        lines.append(f"  Auth: {context.api_key_env} (NOT SET)")

    return "\n".join(lines)
