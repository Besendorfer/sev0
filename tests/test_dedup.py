import time

import pytest

from sev0.dedup import DedupStore


@pytest.fixture
async def dedup_store(tmp_path):
    store = DedupStore(db_path=str(tmp_path / "test_dedup.db"), ttl_hours=1)
    await store.initialize()
    yield store
    await store.close()


class TestDedupStore:
    async def test_first_seen_not_duplicate(self, dedup_store):
        assert await dedup_store.is_duplicate("abc123") is False

    async def test_second_seen_is_duplicate(self, dedup_store):
        await dedup_store.is_duplicate("abc123")
        assert await dedup_store.is_duplicate("abc123") is True

    async def test_different_fingerprints_not_duplicate(self, dedup_store):
        await dedup_store.is_duplicate("abc123")
        assert await dedup_store.is_duplicate("def456") is False

    async def test_expired_entry_not_duplicate(self, dedup_store):
        # Set a very short TTL
        dedup_store._ttl_seconds = 0.1
        await dedup_store.is_duplicate("abc123")
        time.sleep(0.2)
        assert await dedup_store.is_duplicate("abc123") is False

    async def test_record_ticket(self, dedup_store):
        await dedup_store.is_duplicate("abc123")
        await dedup_store.record_ticket("abc123", "https://jira.example.com/OPS-42")
        # Should not raise
        assert await dedup_store.is_duplicate("abc123") is True

    async def test_cleanup_expired(self, dedup_store):
        dedup_store._ttl_seconds = 0.1
        await dedup_store.is_duplicate("abc123")
        await dedup_store.is_duplicate("def456")
        time.sleep(0.2)
        removed = await dedup_store.cleanup_expired()
        assert removed == 2
