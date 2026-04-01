from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from sev0.adapters.actions.base import AbstractAction
from sev0.models import ActionResult, TriageResult
from sev0.registry import register_action

logger = logging.getLogger(__name__)

_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")

_SEVERITY_TO_JIRA_PRIORITY = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Lowest",
}


def _markdown_to_adf(markdown: str) -> dict:
    """Convert simple markdown to Atlassian Document Format (ADF).

    Handles paragraphs and code blocks. For a PoC this covers the most
    common patterns in triage ticket bodies.
    """
    doc: dict[str, Any] = {
        "version": 1,
        "type": "doc",
        "content": [],
    }

    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Code block
        if line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            doc["content"].append({
                "type": "codeBlock",
                "content": [{"type": "text", "text": "\n".join(code_lines)}],
            })
            continue

        # Heading
        if line.startswith("## "):
            doc["content"].append({
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": line[3:]}],
            })
            i += 1
            continue

        if line.startswith("# "):
            doc["content"].append({
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": line[2:]}],
            })
            i += 1
            continue

        # Bold text within paragraphs
        if line.startswith("**") and "**" in line[2:]:
            doc["content"].append({
                "type": "paragraph",
                "content": [{"type": "text", "text": line.replace("**", ""), "marks": [{"type": "strong"}]}],
            })
            i += 1
            continue

        # Regular paragraph
        if line.strip():
            doc["content"].append({
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            })

        i += 1

    return doc


@register_action("jira")
class JiraAction(AbstractAction):
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        issue_type: str = "Bug",
        default_labels: list[str] | None = None,
        **kwargs: Any,
    ):
        self._base_url = base_url.rstrip("/")
        self._project_key = project_key
        self._issue_type = issue_type
        self._default_labels = default_labels or ["auto-triage"]
        self._auth = (email, api_token)

    async def execute(self, result: TriageResult) -> ActionResult:
        payload = {
            "fields": {
                "project": {"key": self._project_key},
                "summary": result.ticket_title[:255],
                "description": _markdown_to_adf(result.ticket_body),
                "issuetype": {"name": self._issue_type},
                "labels": self._default_labels + [
                    f"severity-{result.severity.value}",
                    f"service-{result.event.service}",
                ],
                "priority": {"name": self._severity_to_jira_priority(result.severity.value)},
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/rest/api/3/issue",
                    json=payload,
                    auth=self._auth,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    issue_key = data["key"]
                    url = f"{self._base_url}/browse/{issue_key}"
                    logger.info("Created Jira issue: %s", issue_key)

                    # Add a comment with suggested owner if present
                    if result.suggested_owner:
                        await self._add_comment(
                            client, issue_key,
                            f"AI triage suggests this should be owned by: {result.suggested_owner}"
                        )

                    return ActionResult(
                        action_type="jira",
                        success=True,
                        url=url,
                        resource_id=issue_key,
                    )
                else:
                    logger.error("Jira create failed (HTTP %d)", resp.status_code)
                    return ActionResult(
                        action_type="jira",
                        success=False,
                        error=f"HTTP {resp.status_code}",
                    )

        except Exception as e:
            logger.error("Jira request failed: %s", e)
            return ActionResult(action_type="jira", success=False, error=str(e))

    async def _add_comment(self, client: httpx.AsyncClient, issue_key: str, text: str) -> None:
        if not _ISSUE_KEY_RE.match(issue_key):
            logger.error("Invalid issue key format: %s", issue_key)
            return
        try:
            await client.post(
                f"{self._base_url}/rest/api/3/issue/{issue_key}/comment",
                json={"body": _markdown_to_adf(text)},
                auth=self._auth,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
        except Exception as e:
            logger.warning("Failed to add comment to %s: %s", issue_key, e)

    @staticmethod
    def _severity_to_jira_priority(severity: str) -> str:
        return _SEVERITY_TO_JIRA_PRIORITY.get(severity, "Medium")
