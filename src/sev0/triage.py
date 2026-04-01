from __future__ import annotations

import json
import logging
import re

import anthropic

from sev0.models import AlertEvent, Severity, TriageResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert on-call triage engineer. Your job is to analyze error logs and alerts, \
determine severity, identify the likely root cause, and produce a structured triage report.

You MUST respond with ONLY valid JSON matching this schema — no markdown fencing, no extra text:

{
  "severity": "critical | high | medium | low | info",
  "confidence": <float 0.0 to 1.0>,
  "summary": "<one-line summary of the issue>",
  "root_cause": "<likely root cause analysis>",
  "is_actionable": <true if a human should investigate>,
  "needs_immediate_attention": <true if this is actively causing user impact>,
  "suggested_owner": "<team or service owner, or null if unknown>",
  "recommended_action": "<what the on-call engineer should do next>",
  "ticket_title": "<concise title for a bug ticket>",
  "ticket_body": "<markdown-formatted body for a bug ticket with context, impact, and next steps>"
}

Severity guidelines:
- critical: Data loss, full outage, security breach. Confidence >= 0.8.
- high: Partial outage, degraded performance affecting many users. Confidence >= 0.6.
- medium: Errors affecting a subset of users or a non-critical service.
- low: Intermittent errors, edge cases, or low-impact issues.
- info: Transient/self-healing issues, expected errors, or noise.

Confidence calibration:
- 0.9+: Clear, well-known error pattern with obvious root cause.
- 0.7-0.9: Strong signals but some ambiguity.
- 0.5-0.7: Reasonable hypothesis but limited evidence.
- <0.5: Guessing — flag this clearly in the summary.\
"""


def _build_user_message(event: AlertEvent) -> str:
    parts = [
        f"Source: {event.source_type}",
        f"Service: {event.service}",
        f"Environment: {event.environment}",
        f"Timestamp: {event.timestamp.isoformat()}",
    ]
    if event.log_group:
        parts.append(f"Log Group: {event.log_group}")
    if event.occurrence_count > 1:
        parts.append(f"Occurrences: {event.occurrence_count}")
    if event.tags:
        parts.append(f"Tags: {json.dumps(event.tags)}")

    parts.append(f"\nError Message:\n```\n{event.message}\n```")

    if event.stack_trace:
        parts.append(f"\nStack Trace:\n```\n{event.stack_trace}\n```")

    return "\n".join(parts)


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_response(text: str) -> dict:
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse triage response as JSON: {text[:200]}")


def _safe_fallback(event: AlertEvent) -> TriageResult:
    return TriageResult(
        event=event,
        severity=Severity.MEDIUM,
        confidence=0.1,
        summary=f"[AUTO-TRIAGE FAILED] Could not parse AI response for: {event.title}",
        root_cause="Triage failed — manual review required.",
        is_actionable=True,
        needs_immediate_attention=False,
        suggested_owner=None,
        recommended_action="Manually review the alert and triage.",
        ticket_title=f"[Manual Triage Needed] {event.title}",
        ticket_body=f"Auto-triage failed for this alert. Please review manually.\n\n"
                    f"**Error:**\n```\n{event.message[:1000]}\n```",
    )


async def triage_event(
    event: AlertEvent,
    model: str = "claude-sonnet-4-6",
) -> TriageResult:
    client = anthropic.AsyncAnthropic()

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(event)}],
        )

        raw_text = response.content[0].text
        parsed = _parse_response(raw_text)

        return TriageResult(
            event=event,
            severity=Severity(parsed["severity"]),
            confidence=parsed["confidence"],
            summary=parsed["summary"],
            root_cause=parsed["root_cause"],
            is_actionable=parsed["is_actionable"],
            needs_immediate_attention=parsed["needs_immediate_attention"],
            suggested_owner=parsed.get("suggested_owner"),
            recommended_action=parsed["recommended_action"],
            ticket_title=parsed["ticket_title"],
            ticket_body=parsed["ticket_body"],
        )

    except Exception as e:
        logger.error("Triage failed for event %s: %s", event.id, e)
        return _safe_fallback(event)
