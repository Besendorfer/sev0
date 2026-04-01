from datetime import datetime

from sev0.models import AlertEvent, Severity, TriageResult, _normalize_message


class TestNormalizeMessage:
    def test_strips_timestamps(self):
        msg = "ERROR 2026-04-01T08:30:00.123Z Something failed"
        assert "<TS>" in _normalize_message(msg)
        assert "2026-04-01" not in _normalize_message(msg)

    def test_strips_uuids(self):
        msg = "Failed for request a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert "<UUID>" in _normalize_message(msg)

    def test_strips_ips(self):
        msg = "Connection refused to 192.168.1.42"
        assert "<IP>" in _normalize_message(msg)

    def test_strips_long_numbers(self):
        msg = "Timeout for request 1234567890"
        assert "<NUM>" in _normalize_message(msg)

    def test_uses_first_line_only(self):
        msg = "First line error\nSecond line with details"
        result = _normalize_message(msg)
        assert "Second line" not in result

    def test_preserves_meaningful_text(self):
        msg = "NullPointerException in UserService.getProfile"
        assert _normalize_message(msg) == msg


class TestAlertEvent:
    def test_fingerprint_deterministic(self, sample_alert):
        fp1 = sample_alert.fingerprint
        fp2 = sample_alert.fingerprint
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_stable_across_timestamps(self):
        """Same error at different times should produce the same fingerprint."""
        event1 = AlertEvent(
            id="a",
            source_type="cloudwatch",
            service="api",
            timestamp=datetime(2026, 1, 1),
            title="Error",
            message="ERROR 2026-01-01T00:00:00Z NullPointerException in getProfile",
        )
        event2 = AlertEvent(
            id="b",
            source_type="cloudwatch",
            service="api",
            timestamp=datetime(2026, 1, 2),
            title="Error",
            message="ERROR 2026-01-02T12:00:00Z NullPointerException in getProfile",
        )
        assert event1.fingerprint == event2.fingerprint

    def test_fingerprint_differs_across_services(self):
        event1 = AlertEvent(
            id="a",
            source_type="cloudwatch",
            service="api-a",
            timestamp=datetime(2026, 1, 1),
            title="Error",
            message="NullPointerException",
        )
        event2 = AlertEvent(
            id="b",
            source_type="cloudwatch",
            service="api-b",
            timestamp=datetime(2026, 1, 1),
            title="Error",
            message="NullPointerException",
        )
        assert event1.fingerprint != event2.fingerprint


class TestSeverity:
    def test_severity_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.INFO.value == "info"

    def test_severity_from_string(self):
        assert Severity("high") == Severity.HIGH
