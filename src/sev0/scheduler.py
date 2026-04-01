from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sev0.config import AppConfig
from sev0.engine import Engine

logger = logging.getLogger(__name__)


def create_scheduler(config: AppConfig, engine: Engine) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    for i, entry in enumerate(config.schedule):
        trigger = CronTrigger.from_crontab(entry.cron)
        scheduler.add_job(
            engine.sweep,
            trigger=trigger,
            id=f"sweep_{i}",
            name=f"Scheduled sweep ({entry.cron})",
            replace_existing=True,
        )
        logger.info("Scheduled sweep: %s", entry.cron)

    # Daily cleanup of expired dedup entries
    scheduler.add_job(
        _cleanup_dedup,
        trigger=CronTrigger(hour=3, minute=0),
        id="dedup_cleanup",
        name="Dedup store cleanup",
        kwargs={"engine": engine},
        replace_existing=True,
    )

    return scheduler


async def _cleanup_dedup(engine: Engine) -> None:
    if engine._dedup:
        removed = await engine._dedup.cleanup_expired()
        logger.info("Dedup cleanup: removed %d expired entries", removed)
