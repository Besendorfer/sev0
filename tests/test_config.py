import os
import tempfile
from pathlib import Path

import pytest
import yaml

from sev0.config import AppConfig, _interpolate_env, load_config


class TestEnvInterpolation:
    def test_simple_interpolation(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert _interpolate_env("${MY_VAR}") == "hello"

    def test_default_value(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _interpolate_env("${MISSING_VAR:fallback}") == "fallback"

    def test_missing_no_default_raises(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ValueError, match="MISSING_VAR"):
            _interpolate_env("${MISSING_VAR}")

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        result = _interpolate_env("http://${HOST}:${PORT}")
        assert result == "http://localhost:8080"

    def test_no_vars_passthrough(self):
        assert _interpolate_env("plain text") == "plain text"


class TestLoadConfig:
    def test_loads_minimal_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "triage": {"model": "claude-sonnet-4-6"},
        }))
        config = load_config(config_file)
        assert config.triage.model == "claude-sonnet-4-6"
        assert config.sources == []
        assert config.schedule == []

    def test_loads_full_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEAMS_URL", "https://teams.example.com/webhook")
        monkeypatch.setenv("JIRA_TOKEN", "secret123")

        raw = {
            "sources": [
                {"type": "cloudwatch", "region": "us-west-2", "log_groups": ["/ecs/svc"]},
            ],
            "channels": [
                {"type": "teams", "webhook_url": "${TEAMS_URL}"},
            ],
            "actions": [
                {
                    "type": "jira",
                    "base_url": "https://jira.example.com",
                    "email": "bot@co.com",
                    "api_token": "${JIRA_TOKEN}",
                    "project_key": "OPS",
                },
            ],
            "triage": {"severity_threshold": "high", "max_events_per_sweep": 20},
            "dedup": {"ttl_hours": 48},
            "schedule": [{"cron": "0 9 * * *"}],
        }

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(raw))
        config = load_config(config_file)

        assert len(config.sources) == 1
        assert config.sources[0].type == "cloudwatch"
        assert config.sources[0].params["region"] == "us-west-2"

        assert config.channels[0].params["webhook_url"] == "https://teams.example.com/webhook"
        assert config.actions[0].params["api_token"] == "secret123"
        assert config.triage.severity_threshold == "high"
        assert config.dedup.ttl_hours == 48
        assert config.schedule[0].cron == "0 9 * * *"
