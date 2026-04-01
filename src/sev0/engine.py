from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sev0.adapters.actions.base import AbstractAction
from sev0.adapters.channels.base import AbstractChannel
from sev0.adapters.sources.base import AbstractSource
from sev0.config import AppConfig
from sev0.dedup import DedupStore
from sev0.models import AlertEvent, Severity, TriageResult
from sev0.registry import get_action, get_channel, get_source
from sev0.triage import triage_event

logger = logging.getLogger(__name__)

# Map severity names to a rank for threshold comparison
_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class Engine:
    def __init__(self, config: AppConfig):
        self._config = config
        self._sources: list[AbstractSource] = []
        self._channels: list[AbstractChannel] = []
        self._actions: list[AbstractAction] = []
        self._dedup: DedupStore | None = None
        self._severity_threshold = Severity(config.triage.severity_threshold)

    async def initialize(self) -> None:
        # Import adapters to trigger registration
        import sev0.adapters  # noqa: F401

        # Instantiate sources
        for source_cfg in self._config.sources:
            source = get_source(source_cfg.type, **source_cfg.params)
            self._sources.append(source)
            logger.info("Loaded source: %s", source_cfg.type)

        # Instantiate channels
        for channel_cfg in self._config.channels:
            channel = get_channel(channel_cfg.type, **channel_cfg.params)
            self._channels.append(channel)
            logger.info("Loaded channel: %s", channel_cfg.type)

        # Instantiate actions
        for action_cfg in self._config.actions:
            action = get_action(action_cfg.type, **action_cfg.params)
            self._actions.append(action)
            logger.info("Loaded action: %s", action_cfg.type)

        # Initialize dedup store
        self._dedup = DedupStore(
            db_path=self._config.dedup.db_path,
            ttl_hours=self._config.dedup.ttl_hours,
        )
        await self._dedup.initialize()
        logger.info("Engine initialized with %d sources, %d channels, %d actions",
                     len(self._sources), len(self._channels), len(self._actions))

    async def shutdown(self) -> None:
        if self._dedup:
            await self._dedup.close()

    async def sweep(self) -> list[TriageResult]:
        """Flow 1: Scheduled sweep — pull alerts from all sources and process them."""
        logger.info("Starting sweep...")
        since = datetime.now() - timedelta(minutes=self._config.sources[0].params.get("lookback_minutes", 480) if self._config.sources else 480)

        # Fetch from all sources in parallel
        fetch_tasks = [source.fetch_alerts(since) for source in self._sources]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        all_events: list[AlertEvent] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Source fetch failed: %s", result)
            else:
                all_events.extend(result)

        logger.info("Fetched %d total events across all sources", len(all_events))

        # Cap events per sweep
        max_events = self._config.triage.max_events_per_sweep
        if len(all_events) > max_events:
            logger.warning("Capping sweep from %d to %d events", len(all_events), max_events)
            all_events = all_events[:max_events]

        # Process each event through the pipeline
        triage_results = []
        for event in all_events:
            result = await self._process(event)
            if result:
                triage_results.append(result)

        logger.info("Sweep complete: %d events processed, %d actionable", len(all_events), len(triage_results))
        return triage_results

    async def handle_alert(self, event: AlertEvent) -> TriageResult | None:
        """Flow 2: Reactive — process a single incoming alert."""
        return await self._process(event)

    async def start_listeners(self) -> None:
        """Start all channel listeners for Flow 2 (reactive alerts)."""
        tasks = [self._run_listener(channel) for channel in self._channels]
        await asyncio.gather(*tasks)

    async def _run_listener(self, channel: AbstractChannel) -> None:
        logger.info("Starting listener for channel: %s", type(channel).__name__)
        try:
            async for event in channel.listen():
                try:
                    await self.handle_alert(event)
                except Exception as e:
                    logger.error("Error handling alert from listener: %s", e)
        except Exception as e:
            logger.error("Channel listener crashed: %s", e)

    async def _process(self, event: AlertEvent) -> TriageResult | None:
        """Shared pipeline: dedup → triage → act → notify."""
        assert self._dedup is not None

        # 1. Dedup check
        if await self._dedup.is_duplicate(event.fingerprint):
            logger.debug("Skipping duplicate: %s", event.fingerprint)
            return None

        # 2. AI triage
        result = await triage_event(event, model=self._config.triage.model)
        logger.info(
            "Triaged [%s] (confidence: %.0f%%): %s",
            result.severity.value, result.confidence * 100, result.summary,
        )

        # 3. Check severity threshold
        if _SEVERITY_RANK.get(result.severity, 0) < _SEVERITY_RANK.get(self._severity_threshold, 0):
            logger.debug("Below severity threshold (%s < %s), skipping actions",
                        result.severity.value, self._severity_threshold.value)
            return result

        # 4. Execute actions (create tickets) if actionable
        if result.is_actionable:
            for action in self._actions:
                action_result = await action.execute(result)
                result.action_results.append(action_result)
                if action_result.success and action_result.url:
                    await self._dedup.record_ticket(event.fingerprint, action_result.url)

        # 5. Notify channels
        for channel in self._channels:
            try:
                await channel.notify(result)
            except Exception as e:
                logger.error("Failed to notify channel %s: %s", type(channel).__name__, e)

        return result
