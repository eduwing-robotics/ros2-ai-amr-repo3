from __future__ import annotations

import pytest

from app.event_store import InMemoryEventStore


def test_event_store_is_bounded_and_returns_newest_events_first():
    store = InMemoryEventStore(maxlen=2)

    store.add({"event_id": "oldest", "source": "tb3_1_picam"})
    store.add({"event_id": "middle", "source": "tb3_1_picam"})
    store.add({"event_id": "newest", "source": "tb3_2_picam"})

    assert len(store) == 2
    assert store.stats() == {"current_size": 2, "max_size": 2}
    assert [event["event_id"] for event in store.latest(limit=10)] == ["newest", "middle"]
    assert [event["event_id"] for event in store.latest(source="tb3_1_picam")] == ["middle"]


def test_event_store_rejects_unbounded_configuration():
    with pytest.raises(ValueError, match="maxlen must be positive"):
        InMemoryEventStore(maxlen=0)
