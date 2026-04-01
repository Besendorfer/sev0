import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sev0.models import Severity
from sev0.triage import _parse_response, triage_event


class TestParseResponse:
    def test_parses_clean_json(self):
        data = {"severity": "high", "summary": "test"}
        result = _parse_response(json.dumps(data))
        assert result == data

    def test_parses_json_in_code_block(self):
        data = {"severity": "high", "summary": "test"}
        text = f"```json\n{json.dumps(data)}\n```"
        result = _parse_response(text)
        assert result == data

    def test_parses_json_in_plain_code_block(self):
        data = {"severity": "medium"}
        text = f"```\n{json.dumps(data)}\n```"
        result = _parse_response(text)
        assert result == data

    def test_raises_on_garbage(self):
        with pytest.raises(ValueError, match="Could not parse"):
            _parse_response("this is not json at all")


class TestTriageEvent:
    async def test_successful_triage(self, sample_alert):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "severity": "high",
            "confidence": 0.85,
            "summary": "NullPointerException in user profile endpoint",
            "root_cause": "Null user object passed to getProfile",
            "is_actionable": True,
            "needs_immediate_attention": False,
            "suggested_owner": "backend-team",
            "recommended_action": "Add null check in UserService.getProfile",
            "ticket_title": "NPE in UserService.getProfile",
            "ticket_body": "## Issue\nNullPointerException when fetching user profile.",
        }))]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("sev0.triage.anthropic.AsyncAnthropic", return_value=mock_client):
            result = await triage_event(sample_alert)

        assert result.severity == Severity.HIGH
        assert result.confidence == 0.85
        assert result.is_actionable is True
        assert "NullPointerException" in result.summary

    async def test_fallback_on_api_error(self, sample_alert):
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

        with patch("sev0.triage.anthropic.AsyncAnthropic", return_value=mock_client):
            result = await triage_event(sample_alert)

        assert result.severity == Severity.MEDIUM
        assert result.confidence == 0.1
        assert "AUTO-TRIAGE FAILED" in result.summary
        assert result.is_actionable is True
