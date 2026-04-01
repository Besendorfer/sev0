from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, computed_field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Patterns used to normalize error messages before fingerprinting
_NORMALIZE_PATTERNS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\d.Z:+-]*"), "<TS>"),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<UUID>"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b\d{6,}\b"), "<NUM>"),
]


def _normalize_message(message: str) -> str:
    line = message.split("\n", 1)[0]
    for pattern, replacement in _NORMALIZE_PATTERNS:
        line = pattern.sub(replacement, line)
    return line.strip()


class AlertEvent(BaseModel):
    id: str
    source_type: str
    service: str
    environment: str = "unknown"
    timestamp: datetime
    severity_raw: str = ""
    title: str
    message: str
    stack_trace: str = ""
    log_group: str = ""
    tags: dict[str, str] = {}
    metadata: dict[str, Any] = {}
    occurrence_count: int = 1

    @computed_field
    @property
    def fingerprint(self) -> str:
        normalized = _normalize_message(self.message)
        raw = f"{self.source_type}:{self.service}:{normalized}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ActionResult(BaseModel):
    action_type: str
    success: bool
    url: str = ""
    resource_id: str = ""
    error: str = ""


class TriageResult(BaseModel):
    event: AlertEvent
    severity: Severity
    confidence: float
    summary: str
    root_cause: str
    is_actionable: bool
    needs_immediate_attention: bool
    suggested_owner: str | None = None
    recommended_action: str
    ticket_title: str
    ticket_body: str
    action_results: list[ActionResult] = []
