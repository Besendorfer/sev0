from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()

_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _interpolate_env(value: str) -> str:
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        result = os.environ.get(var_name)
        if result is None:
            if default is not None:
                return default
            raise ValueError(f"Environment variable {var_name!r} is not set and has no default")
        return result
    return _ENV_PATTERN.sub(replacer, value)


def _interpolate_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return _interpolate_env(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(v) for v in obj]
    return obj


class SourceConfig(BaseModel):
    type: str
    params: dict[str, Any] = {}

    @field_validator("params", mode="before")
    @classmethod
    def collect_extra_into_params(cls, v: Any, info: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else {}


class ChannelConfig(BaseModel):
    type: str
    params: dict[str, Any] = {}

    @field_validator("params", mode="before")
    @classmethod
    def collect_extra_into_params(cls, v: Any, info: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else {}


class ActionConfig(BaseModel):
    type: str
    params: dict[str, Any] = {}

    @field_validator("params", mode="before")
    @classmethod
    def collect_extra_into_params(cls, v: Any, info: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else {}


class TriageConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    severity_threshold: str = "medium"
    max_events_per_sweep: int = 50


class DedupConfig(BaseModel):
    db_path: str = "./data/dedup.db"
    ttl_hours: int = 72


class ScheduleEntry(BaseModel):
    cron: str


class AppConfig(BaseModel):
    sources: list[SourceConfig] = []
    channels: list[ChannelConfig] = []
    actions: list[ActionConfig] = []
    triage: TriageConfig = TriageConfig()
    dedup: DedupConfig = DedupConfig()
    schedule: list[ScheduleEntry] = []


def _flatten_adapter_config(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    adapter_type = raw.pop("type")
    return adapter_type, raw


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f) or {}

    raw = _interpolate_recursive(raw)

    # Flatten adapter configs: pull 'type' out and put everything else into 'params'
    for key in ("sources", "channels", "actions"):
        if key in raw:
            normalized = []
            for entry in raw[key]:
                entry = dict(entry)
                adapter_type = entry.pop("type")
                normalized.append({"type": adapter_type, "params": entry})
            raw[key] = normalized

    return AppConfig.model_validate(raw)
