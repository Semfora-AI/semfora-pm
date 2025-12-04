"""Ticket data models for Semfora PM."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import warnings
import yaml
from pathlib import Path


class TicketStatus(Enum):
    """Ticket status matching Linear workflow states."""
    BACKLOG = "Backlog"
    TODO = "Todo"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    DONE = "Done"
    CANCELED = "Canceled"


class TicketPriority(Enum):
    """Ticket priority levels (Linear uses 0-4, we use 1-4)."""
    URGENT = 1  # Linear: 1
    HIGH = 2    # Linear: 2
    MEDIUM = 3  # Linear: 3
    LOW = 4     # Linear: 4

    def to_linear(self) -> int:
        """Convert to Linear's priority value."""
        return self.value


class Component(Enum):
    """Semfora components for organizing tickets."""
    ENGINE = "engine"
    ADK = "adk"
    CLI = "cli"
    PM = "pm"
    DOCS = "docs"
    INFRA = "infra"


@dataclass
class Ticket:
    """Represents a Semfora project ticket."""

    # Required fields
    id: str  # Local ID like "engine-001"
    title: str
    description: str
    component: Component

    # Optional fields with defaults
    priority: TicketPriority = TicketPriority.MEDIUM
    status: TicketStatus = TicketStatus.BACKLOG
    labels: list[str] = field(default_factory=list)
    estimate: Optional[int] = None  # Story points
    phase: Optional[str] = None  # e.g., "phase-1", "phase-2"
    depends_on: list[str] = field(default_factory=list)  # List of ticket IDs
    blocks: list[str] = field(default_factory=list)  # List of ticket IDs

    # Linear tracking
    linear_id: Optional[str] = None  # Linear's issue ID once synced
    linear_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "component": self.component.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "labels": self.labels,
            "estimate": self.estimate,
            "phase": self.phase,
            "depends_on": self.depends_on,
            "blocks": self.blocks,
            "linear_id": self.linear_id,
            "linear_url": self.linear_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        """Create Ticket from dictionary."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            component=Component(data["component"]),
            priority=TicketPriority(data.get("priority", 3)),
            status=TicketStatus(data.get("status", "Backlog")),
            labels=data.get("labels", []),
            estimate=data.get("estimate"),
            phase=data.get("phase"),
            depends_on=data.get("depends_on", []),
            blocks=data.get("blocks", []),
            linear_id=data.get("linear_id"),
            linear_url=data.get("linear_url"),
        )


def load_tickets(tickets_dir: Path) -> list[Ticket]:
    """
    DEPRECATED: Load all tickets from YAML files in directory.

    This function is deprecated. Linear is now the source of truth.
    Use LinearClient.get_team_issues() instead.
    """
    warnings.warn(
        "load_tickets() is deprecated. Use LinearClient.get_team_issues() instead. "
        "Linear is the source of truth - no local YAML files.",
        DeprecationWarning,
        stacklevel=2,
    )
    tickets = []

    for yaml_file in tickets_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        if "tickets" in data:
            for ticket_data in data["tickets"]:
                tickets.append(Ticket.from_dict(ticket_data))

    return tickets


def save_tickets(tickets: list[Ticket], filepath: Path) -> None:
    """
    DEPRECATED: Save tickets to YAML file.

    This function is deprecated. Linear is now the source of truth.
    Use LinearClient.update_issue() instead.
    """
    warnings.warn(
        "save_tickets() is deprecated. Use LinearClient.update_issue() instead. "
        "Linear is the source of truth - no local YAML files.",
        DeprecationWarning,
        stacklevel=2,
    )
    data = {
        "tickets": [t.to_dict() for t in tickets]
    }

    with open(filepath, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
