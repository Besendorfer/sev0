from __future__ import annotations

from abc import ABC, abstractmethod

from sev0.models import ActionResult, TriageResult


class AbstractAction(ABC):
    @abstractmethod
    async def execute(self, result: TriageResult) -> ActionResult:
        """Take action on a triage result (e.g., create a ticket). Returns result with URL/ID."""
        ...
