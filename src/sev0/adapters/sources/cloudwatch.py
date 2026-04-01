from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

import boto3

from sev0.adapters.sources.base import AbstractSource
from sev0.models import AlertEvent
from sev0.registry import register_source

logger = logging.getLogger(__name__)


@register_source("cloudwatch")
class CloudWatchSource(AbstractSource):
    def __init__(
        self,
        region: str = "us-east-1",
        log_groups: list[str] | None = None,
        query: str = "fields @timestamp, @message | filter @message like /ERROR|Exception/ | sort @timestamp desc | limit 100",
        lookback_minutes: int = 480,
        **kwargs: Any,
    ):
        self._region = region
        self._log_groups = log_groups or []
        self._query = query
        self._lookback_minutes = lookback_minutes
        self._client = boto3.client("logs", region_name=region)

    async def fetch_alerts(self, since: datetime) -> list[AlertEvent]:
        loop = asyncio.get_event_loop()
        events: list[AlertEvent] = []

        for log_group in self._log_groups:
            try:
                group_events = await loop.run_in_executor(
                    None, self._query_log_group, log_group, since
                )
                events.extend(group_events)
            except Exception as e:
                logger.error("Failed to query log group %s: %s", log_group, e)

        logger.info("Fetched %d alerts from CloudWatch across %d log groups", len(events), len(self._log_groups))
        return events

    def _query_log_group(self, log_group: str, since: datetime) -> list[AlertEvent]:
        start_time = int(since.timestamp() * 1000)
        end_time = int(datetime.now().timestamp() * 1000)

        response = self._client.start_query(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            queryString=self._query,
        )
        query_id = response["queryId"]

        # Poll for query completion
        while True:
            result = self._client.get_query_results(queryId=query_id)
            status = result["status"]
            if status in ("Complete", "Failed", "Cancelled", "Timeout"):
                break
            import time
            time.sleep(0.5)

        if status != "Complete":
            logger.warning("CloudWatch query for %s ended with status: %s", log_group, status)
            return []

        events = []
        for row in result.get("results", []):
            fields = {f["field"]: f["value"] for f in row}
            timestamp_str = fields.get("@timestamp", "")
            message = fields.get("@message", "")

            if not message:
                continue

            # Extract service name from log group path
            service = log_group.rsplit("/", 1)[-1]

            # Try to extract a meaningful title from the first line
            first_line = message.split("\n", 1)[0][:200]

            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = datetime.now()

            events.append(AlertEvent(
                id=f"cw-{uuid.uuid4().hex[:12]}",
                source_type="cloudwatch",
                service=service,
                timestamp=ts,
                title=first_line,
                message=message,
                log_group=log_group,
                metadata=fields,
            ))

        return events
