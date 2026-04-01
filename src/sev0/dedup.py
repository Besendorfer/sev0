from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_alerts (
    fingerprint TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    last_ticket_url TEXT DEFAULT ''
);
"""


class DedupStore:
    def __init__(self, db_path: str, ttl_hours: int = 72):
        self._db_path = db_path
        self._ttl_seconds = ttl_hours * 3600
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def is_duplicate(self, fingerprint: str) -> bool:
        assert self._db is not None
        now = time.time()
        cutoff = now - self._ttl_seconds

        cursor = await self._db.execute(
            "SELECT last_seen, count FROM seen_alerts WHERE fingerprint = ?",
            (fingerprint,),
        )
        row = await cursor.fetchone()

        if row is not None:
            last_seen, count = row
            if last_seen >= cutoff:
                # Still within TTL window — update and mark as duplicate
                await self._db.execute(
                    "UPDATE seen_alerts SET last_seen = ?, count = ? WHERE fingerprint = ?",
                    (now, count + 1, fingerprint),
                )
                await self._db.commit()
                return True
            else:
                # Expired — treat as new, reset
                await self._db.execute(
                    "UPDATE seen_alerts SET first_seen = ?, last_seen = ?, count = 1, last_ticket_url = '' WHERE fingerprint = ?",
                    (now, now, fingerprint),
                )
                await self._db.commit()
                return False

        # Never seen — insert
        await self._db.execute(
            "INSERT INTO seen_alerts (fingerprint, first_seen, last_seen, count) VALUES (?, ?, ?, 1)",
            (fingerprint, now, now),
        )
        await self._db.commit()
        return False

    async def record_ticket(self, fingerprint: str, ticket_url: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE seen_alerts SET last_ticket_url = ? WHERE fingerprint = ?",
            (ticket_url, fingerprint),
        )
        await self._db.commit()

    async def cleanup_expired(self) -> int:
        assert self._db is not None
        cutoff = time.time() - self._ttl_seconds
        cursor = await self._db.execute(
            "DELETE FROM seen_alerts WHERE last_seen < ?", (cutoff,)
        )
        await self._db.commit()
        return cursor.rowcount
