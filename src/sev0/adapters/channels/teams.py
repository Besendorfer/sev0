from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from aiohttp import web

from sev0.adapters.channels.base import AbstractChannel
from sev0.models import AlertEvent, Severity, TriageResult
from sev0.registry import register_channel

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB
MAX_MESSAGE_LENGTH = 50_000
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

_SEVERITY_COLORS = {
    Severity.CRITICAL: "attention",
    Severity.HIGH: "warning",
    Severity.MEDIUM: "accent",
    Severity.LOW: "good",
    Severity.INFO: "default",
}


def _build_adaptive_card(result: TriageResult) -> dict:
    """Build a Teams Adaptive Card from a triage result."""
    color = _SEVERITY_COLORS.get(result.severity, "default")
    icon = "🚨" if result.severity in (Severity.CRITICAL, Severity.HIGH) else "ℹ️"

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
                                    "text": f"{icon} [{result.severity.value.upper()}] {result.ticket_title}",
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
                                {"title": "Severity", "value": f"{result.severity.value} (confidence: {result.confidence:.0%})"},
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
        webhook_secret: str = "",
        **kwargs: Any,
    ):
        self._webhook_url = webhook_url
        self._listen_port = listen_port
        self._webhook_secret = webhook_secret
        self._alert_queue: asyncio.Queue[AlertEvent] = asyncio.Queue()
        self._request_times: dict[str, deque[float]] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
        return self._client

    async def notify(self, result: TriageResult) -> None:
        card = _build_adaptive_card(result)
        client = await self._get_client()
        resp = await client.post(self._webhook_url, json=card)
        if resp.status_code not in (200, 202):
            logger.error("Teams webhook failed (HTTP %d): %s", resp.status_code, resp.text[:200])
        else:
            logger.info("Notified Teams for: %s", result.ticket_title)

    async def listen(self) -> AsyncIterator[AlertEvent]:
        """Listen for alerts forwarded via Teams incoming messages.

        Starts an aiohttp web server that receives webhook payloads
        from a Teams Outgoing Webhook or Power Automate flow.
        """
        app = web.Application(client_max_size=MAX_CONTENT_LENGTH)
        app.router.add_post("/", self._handle_webhook)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._listen_port)
        await site.start()
        logger.info("Teams listener started on port %d", self._listen_port)

        try:
            while True:
                event = await self._alert_queue.get()
                yield event
        finally:
            await runner.cleanup()

    def _is_rate_limited(self, peer_ip: str) -> bool:
        now = time.time()
        if peer_ip not in self._request_times:
            self._request_times[peer_ip] = deque(maxlen=RATE_LIMIT_REQUESTS)

        dq = self._request_times[peer_ip]
        # Evict expired entries from the front
        while dq and now - dq[0] >= RATE_LIMIT_WINDOW_SECONDS:
            dq.popleft()

        if len(dq) >= RATE_LIMIT_REQUESTS:
            return True
        dq.append(now)

        # Lazy cleanup: drop stale IPs periodically
        if len(self._request_times) > 10_000:
            stale = [ip for ip, d in self._request_times.items() if not d or now - d[-1] >= RATE_LIMIT_WINDOW_SECONDS]
            for ip in stale:
                del self._request_times[ip]

        return False

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        expected = hmac.new(
            self._webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        peer = request.remote or "unknown"

        # Rate limiting
        if self._is_rate_limited(peer):
            logger.warning("Rate limit exceeded for %s", peer)
            return web.Response(status=429, text="Too Many Requests", headers=_SECURITY_HEADERS)

        # Verify webhook signature if a secret is configured
        body = await request.read()
        if self._webhook_secret:
            signature = request.headers.get("X-Webhook-Signature", "")
            if not self._verify_signature(body, signature):
                logger.warning("Invalid webhook signature from %s", peer)
                return web.Response(status=401, text="Unauthorized", headers=_SECURITY_HEADERS)

        # Parse and enqueue
        if body:
            try:
                data = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return web.Response(status=400, text="Bad Request", headers=_SECURITY_HEADERS)
            event = self._parse_teams_message(data)
            if event:
                await self._alert_queue.put(event)

        return web.Response(status=200, text="OK", headers=_SECURITY_HEADERS)

    def _parse_teams_message(self, data: dict) -> AlertEvent | None:
        """Parse a Teams message payload into an AlertEvent.

        Expects the message text to contain error details -- either as a forwarded
        alert or a pasted log snippet.
        """
        text = data.get("text", "") or data.get("body", {}).get("content", "")
        if not text or not isinstance(text, str):
            return None

        # Enforce message length limit
        if len(text) > MAX_MESSAGE_LENGTH:
            logger.warning("Teams message truncated from %d to %d chars", len(text), MAX_MESSAGE_LENGTH)
            text = text[:MAX_MESSAGE_LENGTH]

        return AlertEvent(
            id=f"teams-{uuid.uuid4().hex[:12]}",
            source_type="teams",
            service="unknown",
            timestamp=datetime.now(),
            title=text.split("\n", 1)[0][:200],
            message=text,
        )
