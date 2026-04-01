from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from sev0.models import AlertEvent


class AbstractSource(ABC):
    @abstractmethod
    async def fetch_alerts(self, since: datetime) -> list[AlertEvent]:
        """Pull alerts that occurred since the given timestamp."""
        ...
