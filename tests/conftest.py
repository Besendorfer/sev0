from __future__ import annotations

from datetime import datetime

import pytest

from sev0.models import AlertEvent


@pytest.fixture
def sample_alert() -> AlertEvent:
    return AlertEvent(
        id="test-001",
        source_type="cloudwatch",
        service="my-api",
        environment="production",
        timestamp=datetime(2026, 4, 1, 8, 30, 0),
        severity_raw="ERROR",
        title="NullPointerException in UserService.getProfile",
        message="ERROR 2026-04-01T08:30:00Z [UserService] NullPointerException: Cannot invoke method on null reference\n"
                "  at com.example.UserService.getProfile(UserService.java:42)\n"
                "  at com.example.ApiHandler.handle(ApiHandler.java:18)",
        stack_trace="at com.example.UserService.getProfile(UserService.java:42)\n"
                    "at com.example.ApiHandler.handle(ApiHandler.java:18)",
        log_group="/ecs/my-api",
        tags={"env": "prod", "region": "us-east-1"},
    )


@pytest.fixture
def sample_alert_low_severity() -> AlertEvent:
    return AlertEvent(
        id="test-002",
        source_type="cloudwatch",
        service="my-api",
        environment="production",
        timestamp=datetime(2026, 4, 1, 8, 30, 0),
        title="Connection pool timeout (retried successfully)",
        message="WARN 2026-04-01T08:30:00Z [ConnectionPool] Timeout after 5000ms, retried OK",
        log_group="/ecs/my-api",
    )
