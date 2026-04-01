from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from sev0.adapters.channels.base import AbstractChannel
from sev0.models import AlertEvent, TriageResult
from sev0.registry import register_channel

logger = logging.getLogger(__name__)

_SEVERITY_COLORS = {
    "critical": "attention",
    "high": "warning",
    "medium": "accent",
    "low": "good",
    "info": "default",
}


def _build_adaptive_card(result: TriageResult) -> dict:
    """Build a Teams Adaptive Card from a triage result."""
    severity = result.severity.value
    color = _SEVERITY_COLORS.get(severity, "default")

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "Container",
                            "style": color,
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": f"{'🚨' if severity in ('critical', 'high') else 'ℹ️'} [{severity.upper()}] {result.ticket_title}",
                                    "weight": "bolder",
                                    "size": "medium",
                                    "wrap": True,
                                },
                            ],
                        },
                        {
                            "type": "TextBlock",
                            "text": result.summary,
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Service", "value": result.event.service},
                                {"title": "Severity", "value": f"{severity} (confidence: {result.confidence:.0%})"},
                                {"title": "Root Cause", "value": result.root_cause[:200]},
                                {"title": "Action", "value": result.recommended_action[:200]},
                            ],
                        },
                    ],
                    "actions": [],
                },
            }
        ],
    }

    # Add link to ticket if one was created
    for action_result in result.action_results:
        if action_result.success and action_result.url:
            card["attachments"][0]["content"]["actions"].append({
                "type": "Action.OpenUrl",
                "title": f"View {action_result.action_type.title()} Ticket",
                "url": action_result.url,
            })

    return card


@register_channel("teams")
class TeamsChannel(AbstractChannel):
    def __init__(
        self,
        webhook_url: str,
        listen_port: int = 8089,
        **kwargs: Any,
    ):
        self._webhook_url = webhook_url
        self._listen_port = listen_port
        self._alert_queue: asyncio.Queue[AlertEvent] = asyncio.Queue()

    async def notify(self, result: TriageResult) -> None:
        card = _build_adaptive_card(result)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._webhook_url,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code not in (200, 202):
                logger.error("Teams webhook failed (HTTP %d): %s", resp.status_code, resp.text[:200])
            else:
                logger.info("Notified Teams for: %s", result.ticket_title)

    async def listen(self) -> AsyncIterator[AlertEvent]:
        """Listen for alerts forwarded via Teams incoming messages.

        This starts a lightweight HTTP server that receives webhook payloads
        from a Teams Outgoing Webhook or Power Automate flow.
        """
        server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self._listen_port
        )
        logger.info("Teams listener started on port %d", self._listen_port)

        async with server:
            while True:
                event = await self._alert_queue.get()
                yield event

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            # Read HTTP request
            request_line = await reader.readline()
            headers = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(content_length) if content_length else b""

            # Parse and enqueue
            if body:
                data = json.loads(body)
                event = self._parse_teams_message(data)
                if event:
                    await self._alert_queue.put(event)

            # Send 200 OK
            response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.error("Error handling Teams webhook: %s", e)
        finally:
            writer.close()

    def _parse_teams_message(self, data: dict) -> AlertEvent | None:
        """Parse a Teams message payload into an AlertEvent.

        Expects the message text to contain error details — either as a forwarded
        alert or a pasted log snippet.
        """
        text = data.get("text", "") or data.get("body", {}).get("content", "")
        if not text:
            return None

        return AlertEvent(
            id=f"teams-{uuid.uuid4().hex[:12]}",
            source_type="teams",
            service="unknown",
            timestamp=datetime.now(),
            title=text.split("\n", 1)[0][:200],
            message=text,
        )
