import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sev0.config import load_config
from sev0.engine import Engine
from sev0.models import ActionResult, AlertEvent, Severity, TriageResult


def _make_config(tmp_path, overrides=None):
    raw = {
        "sources": [{"type": "cloudwatch", "region": "us-east-1", "log_groups": ["/test"]}],
        "channels": [{"type": "teams", "webhook_url": "https://fake.webhook.com"}],
        "actions": [
            {
                "type": "jira",
                "base_url": "https://jira.fake.com",
                "email": "bot@co.com",
                "api_token": "token",
                "project_key": "TEST",
            }
        ],
        "triage": {"severity_threshold": "medium"},
        "dedup": {"db_path": str(tmp_path / "dedup.db")},
    }
    if overrides:
        raw.update(overrides)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(raw))
    return load_config(config_file)


def _mock_triage_result(event: AlertEvent, severity: str = "high") -> TriageResult:
    return TriageResult(
        event=event,
        severity=Severity(severity),
        confidence=0.8,
        summary="Test issue",
        root_cause="Test root cause",
        is_actionable=True,
        needs_immediate_attention=False,
        recommended_action="Fix it",
        ticket_title="Test ticket",
        ticket_body="Test body",
    )


class TestEngine:
    async def test_process_skips_duplicates(self, tmp_path, sample_alert):
        config = _make_config(tmp_path)
        engine = Engine(config)

        # Manually initialize dedup only
        from sev0.dedup import DedupStore
        engine._dedup = DedupStore(db_path=str(tmp_path / "dedup.db"), ttl_hours=1)
        await engine._dedup.initialize()

        # First call — not a duplicate
        with patch("sev0.engine.triage_event", new_callable=AsyncMock) as mock_triage:
            mock_triage.return_value = _mock_triage_result(sample_alert)
            engine._actions = [AsyncMock(execute=AsyncMock(return_value=ActionResult(action_type="jira", success=True, url="https://jira.fake.com/TEST-1")))]
            engine._channels = [AsyncMock(notify=AsyncMock())]

            result1 = await engine._process(sample_alert)
            assert result1 is not None

            # Second call — duplicate, should be skipped
            result2 = await engine._process(sample_alert)
            assert result2 is None

        await engine._dedup.close()

    async def test_process_skips_below_threshold(self, tmp_path, sample_alert):
        config = _make_config(tmp_path, {"triage": {"severity_threshold": "high"}})
        engine = Engine(config)

        from sev0.dedup import DedupStore
        engine._dedup = DedupStore(db_path=str(tmp_path / "dedup.db"), ttl_hours=1)
        await engine._dedup.initialize()
        engine._actions = []
        engine._channels = [AsyncMock(notify=AsyncMock())]

        with patch("sev0.engine.triage_event", new_callable=AsyncMock) as mock_triage:
            # Return a "low" severity result — below "high" threshold
            mock_triage.return_value = _mock_triage_result(sample_alert, severity="low")
            result = await engine._process(sample_alert)

        # Should still return the result but not execute actions
        assert result is not None
        assert result.action_results == []
        await engine._dedup.close()
