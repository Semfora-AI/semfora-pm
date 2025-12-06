"""Tests for MCP server tools."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from semfora_pm.mcp_server import get_ticket_summary, get_ticket


class TestGetTicketSummary:
    """Tests for get_ticket_summary MCP tool."""

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_returns_minimal_response(self, mock_get_client):
        """Should return only display-critical fields."""
        mock_client = Mock()
        mock_client.get_issue_by_identifier.return_value = {
            "identifier": "SEM-45",
            "title": "Add authentication to CLI",
            "state": {"name": "In Progress"},
            "priority": 2,
            "assignee": {"name": "John Doe"},
            "description": "Full description here that should NOT be returned",
            "labels": {"nodes": [{"name": "feature"}]},
        }
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket_summary("SEM-45")

        assert "identifier" in result
        assert "title" in result
        assert "state" in result
        assert "priority" in result
        assert "assignee" in result
        # Should NOT include verbose fields
        assert "description" not in result
        assert "labels" not in result
        assert result["identifier"] == "SEM-45"
        assert result["title"] == "Add authentication to CLI"
        assert result["state"] == "In Progress"
        assert result["priority"] == "High"
        assert result["assignee"] == "John Doe"

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_truncates_long_titles(self, mock_get_client):
        """Should truncate titles longer than 50 characters."""
        mock_client = Mock()
        mock_client.get_issue_by_identifier.return_value = {
            "identifier": "SEM-45",
            "title": "This is a very long title that exceeds the fifty character limit for display",
            "state": {"name": "Todo"},
            "priority": 3,
        }
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket_summary("SEM-45")

        assert len(result["title"]) <= 50
        assert result["title"].endswith("...")

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_handles_not_found(self, mock_get_client):
        """Should gracefully handle non-existent tickets."""
        mock_client = Mock()
        mock_client.get_issue_by_identifier.return_value = None
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket_summary("SEM-99999")

        assert "error" in result
        assert result["error"] == "not_found"

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_handles_no_assignee(self, mock_get_client):
        """Should handle tickets without assignee."""
        mock_client = Mock()
        mock_client.get_issue_by_identifier.return_value = {
            "identifier": "SEM-45",
            "title": "Unassigned ticket",
            "state": {"name": "Backlog"},
            "priority": 4,
            "assignee": None,
        }
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket_summary("SEM-45")

        assert result["assignee"] is None

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_response_is_minimal(self, mock_get_client):
        """Should return minimal response for CLI efficiency."""
        mock_client = Mock()
        mock_client.get_issue_by_identifier.return_value = {
            "identifier": "SEM-45",
            "title": "Short title",
            "state": {"name": "Done"},
            "priority": 1,
            "assignee": {"name": "Jane"},
            "description": "Should not appear",
            "url": "https://linear.app/...",
            "labels": {"nodes": []},
            "project": {"name": "Test Project"},
        }
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket_summary("SEM-45")

        # Should only have 5 fields for minimal response
        expected_fields = {"identifier", "title", "state", "priority", "assignee"}
        assert set(result.keys()) == expected_fields

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_formats_priority_correctly(self, mock_get_client):
        """Should format priority numbers to strings."""
        test_cases = [
            (1, "Urgent"),
            (2, "High"),
            (3, "Medium"),
            (4, "Low"),
            (0, "None"),
        ]

        for priority_num, priority_str in test_cases:
            mock_client = Mock()
            mock_client.get_issue_by_identifier.return_value = {
                "identifier": "SEM-45",
                "title": "Test",
                "state": {"name": "Todo"},
                "priority": priority_num,
            }
            mock_context = Mock()
            mock_get_client.return_value = (mock_client, mock_context, None)

            result = get_ticket_summary("SEM-45")
            assert result["priority"] == priority_str, f"Expected {priority_str} for priority {priority_num}"


class TestGetTicket:
    """Tests for existing get_ticket MCP tool."""

    @patch("semfora_pm.mcp_server._get_client_safe")
    def test_returns_full_data(self, mock_get_client):
        """Should return complete ticket info including description."""
        mock_client = Mock()
        mock_client.get_issue_full.return_value = {
            "identifier": "SEM-45",
            "title": "Add authentication",
            "state": {"name": "In Progress"},
            "priority": 2,
            "description": "## Requirements\n- Item 1\n- Item 2",
            "url": "https://linear.app/...",
            "labels": {"nodes": [{"name": "feature"}]},
            "assignee": {"name": "John"},
            "project": {"name": "CLI"},
            "cycle": None,
            "parent": None,
            "children": {"nodes": []},
            "relations": {"nodes": []},
            "estimate": 5,
            "createdAt": "2025-12-01T00:00:00Z",
            "updatedAt": "2025-12-05T00:00:00Z",
        }
        mock_context = Mock()
        mock_get_client.return_value = (mock_client, mock_context, None)

        result = get_ticket("SEM-45")

        # Full ticket should include description
        assert "description" in result
        assert result["description"] == "## Requirements\n- Item 1\n- Item 2"
        assert "url" in result
        assert "labels" in result
