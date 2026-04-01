from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from sev0.models import AlertEvent, TriageResult


class AbstractChannel(ABC):
    @abstractmethod
    async def listen(self) -> AsyncIterator[AlertEvent]:
        """Yield incoming alerts from this channel in real-time."""
        ...

    @abstractmethod
    async def notify(self, result: TriageResult) -> None:
        """Send a triage result notification to this channel."""
        ...
