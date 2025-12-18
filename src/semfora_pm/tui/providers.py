"""Provider abstraction layer for the TUI.

This module provides a unified interface for accessing ticket data
from different providers (Linear, GitHub, Jira, etc.) while also
supporting offline operation using cached data.
"""

from dataclasses import dataclass
from typing import Optional, Protocol
from abc import abstractmethod

from ..external_items import ExternalItem, ExternalItemsManager
from ..pm_config import PMContext


@dataclass
class TicketDetails:
    """Unified ticket details from any provider."""

    provider_id: str  # e.g., "SEM-123", "GH-456"
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    status_category: Optional[str] = None  # todo, in_progress, done, canceled
    priority: Optional[int] = None  # 0-4 scale
    assignee: Optional[str] = None
    labels: list[str] = None
    epic_id: Optional[str] = None
    epic_name: Optional[str] = None
    url: Optional[str] = None
    is_cached: bool = False  # True if from cache, False if live

    def __post_init__(self):
        if self.labels is None:
            self.labels = []

    @classmethod
    def from_external_item(cls, item: ExternalItem) -> "TicketDetails":
        """Create TicketDetails from a cached ExternalItem."""
        return cls(
            provider_id=item.provider_id,
            title=item.title,
            description=item.description,
            status=item.status,
            status_category=item.status_category.value if item.status_category else None,
            priority=item.priority,
            assignee=item.assignee_name or item.assignee,
            labels=item.labels or [],
            epic_id=item.epic_id,
            epic_name=item.epic_name,
            url=item.url,
            is_cached=True,
        )


class ProviderAdapter(Protocol):
    """Protocol for provider adapters.

    All provider adapters must implement this interface to be usable
    by the TUI for fetching ticket details.
    """

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the provider is connected and authenticated."""
        ...

    @abstractmethod
    def get_ticket(self, provider_id: str) -> Optional[TicketDetails]:
        """Get ticket details by provider ID.

        Args:
            provider_id: The provider's ticket ID (e.g., "SEM-123")

        Returns:
            TicketDetails if found, None otherwise
        """
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the name of this provider."""
        ...


class OfflineAdapter:
    """Adapter that uses only cached external_items data.

    This adapter works entirely offline, using data that was previously
    cached when tickets were linked to local plans.
    """

    def __init__(self, external_items_manager: ExternalItemsManager):
        """Initialize the offline adapter.

        Args:
            external_items_manager: Manager for cached external items
        """
        self._manager = external_items_manager

    def is_connected(self) -> bool:
        """Offline adapter is always 'connected' (to local cache)."""
        return True

    def get_ticket(self, provider_id: str) -> Optional[TicketDetails]:
        """Get ticket from local cache."""
        item = self._manager.get_by_provider_id(provider_id)
        if item:
            return TicketDetails.from_external_item(item)
        return None

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "Local Cache"


class LinearAdapter:
    """Adapter for Linear API integration.

    This adapter connects to Linear to fetch live ticket data,
    with fallback to cached data when offline.
    """

    def __init__(
        self,
        context: PMContext,
        external_items_manager: ExternalItemsManager,
    ):
        """Initialize the Linear adapter.

        Args:
            context: PM context with API configuration
            external_items_manager: Manager for caching fetched items
        """
        self._context = context
        self._manager = external_items_manager
        self._client = None
        self._connected = False

        # Try to initialize client
        self._init_client()

    def _init_client(self) -> None:
        """Try to initialize the Linear client."""
        if not self._context.api_key:
            return

        try:
            from ..linear_client import LinearClient

            self._client = LinearClient.from_context(self._context.config_path)
            self._connected = True
        except Exception:
            # Failed to connect, will use cache
            self._connected = False

    def is_connected(self) -> bool:
        """Check if connected to Linear API."""
        return self._connected and self._client is not None

    def get_ticket(self, provider_id: str) -> Optional[TicketDetails]:
        """Get ticket from Linear API or cache.

        First tries to fetch from Linear API. If that fails or is unavailable,
        falls back to cached data.
        """
        # Try live fetch if connected
        if self.is_connected():
            try:
                issue = self._client.get_issue_by_identifier(provider_id)
                if issue:
                    # Cache the result
                    self._cache_issue(issue)
                    return self._issue_to_details(issue, is_cached=False)
            except Exception:
                pass  # Fall through to cache

        # Fallback to cache
        cached = self._manager.get_by_provider_id(provider_id)
        if cached:
            return TicketDetails.from_external_item(cached)

        return None

    def _issue_to_details(self, issue: dict, is_cached: bool = False) -> TicketDetails:
        """Convert Linear issue dict to TicketDetails."""
        from ..external_items import normalize_linear_status, normalize_linear_priority

        state = issue.get("state", {})
        status_category = normalize_linear_status(state.get("type", ""))

        return TicketDetails(
            provider_id=issue.get("identifier", ""),
            title=issue.get("title", ""),
            description=issue.get("description"),
            status=state.get("name"),
            status_category=status_category.value if status_category else None,
            priority=normalize_linear_priority(issue.get("priority")),
            assignee=issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
            labels=[label.get("name", "") for label in issue.get("labels", {}).get("nodes", [])],
            epic_id=issue.get("project", {}).get("id") if issue.get("project") else None,
            epic_name=issue.get("project", {}).get("name") if issue.get("project") else None,
            url=issue.get("url"),
            is_cached=is_cached,
        )

    def _cache_issue(self, issue: dict) -> None:
        """Cache a Linear issue as an external item."""
        from ..external_items import (
            ExternalItem,
            normalize_linear_status,
            normalize_linear_priority,
        )
        import uuid
        from datetime import datetime

        state = issue.get("state", {})

        item = ExternalItem(
            id=str(uuid.uuid4()),
            project_id=self._manager._project_id,
            provider_id=issue.get("identifier", ""),
            item_type="ticket",
            title=issue.get("title", ""),
            description=issue.get("description"),
            status=state.get("name"),
            status_category=normalize_linear_status(state.get("type", "")),
            priority=normalize_linear_priority(issue.get("priority")),
            assignee=issue.get("assignee", {}).get("id") if issue.get("assignee") else None,
            assignee_name=issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
            labels=[label.get("name", "") for label in issue.get("labels", {}).get("nodes", [])],
            epic_id=issue.get("project", {}).get("id") if issue.get("project") else None,
            epic_name=issue.get("project", {}).get("name") if issue.get("project") else None,
            sprint_id=issue.get("cycle", {}).get("id") if issue.get("cycle") else None,
            sprint_name=issue.get("cycle", {}).get("name") if issue.get("cycle") else None,
            url=issue.get("url"),
            provider_data=issue,
            created_at_provider=issue.get("createdAt"),
            updated_at_provider=issue.get("updatedAt"),
            cached_at=datetime.now().isoformat(),
        )

        self._manager.cache_item(item)

    def get_provider_name(self) -> str:
        """Return provider name."""
        return "Linear"


def create_provider_adapter(
    context: PMContext,
    external_items_manager: ExternalItemsManager,
) -> ProviderAdapter:
    """Create the appropriate provider adapter based on context.

    Args:
        context: PM context with provider configuration
        external_items_manager: Manager for cached external items

    Returns:
        An appropriate ProviderAdapter implementation
    """
    provider = context.provider or "local"

    if provider == "linear" and context.api_key:
        return LinearAdapter(context, external_items_manager)

    # Default to offline adapter
    return OfflineAdapter(external_items_manager)
