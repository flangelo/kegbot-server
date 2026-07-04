"""Tests for the kegnet → WebSocket bridge (run_kegnet_listener).

The valuable, bug-prone logic here is meter-name resolution (``_get_tap_info``)
and the end-to-end forward of a ``MeterUpdate`` onto the channel layer. The
Redis pub/sub source is replaced with a fake async iterator so ``listen()`` can
be exercised deterministically without a live publisher.
"""

import asyncio
import json

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer

from pykeg.core.management.commands import run_kegnet_listener as listener
from pykeg.test import factories


@pytest.fixture(autouse=True)
def _clear_tap_info_cache():
    """The meter→tap cache is module-level; isolate it between tests."""
    listener._tap_info_cache.clear()
    yield
    listener._tap_info_cache.clear()


def _seed():
    factories.create_site()
    factories.start_keg("kegboard.flow0")


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_resolves_exact_meter_name():
    await database_sync_to_async(_seed)()

    tap_name, beer_name, _, canonical, ticks_per_ml = await listener._get_tap_info(
        "kegboard.flow0"
    )
    assert tap_name == "Main Tap"
    assert beer_name == "Test Lager"
    assert canonical == "kegboard.flow0"
    assert ticks_per_ml


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_resolves_by_port_suffix():
    await database_sync_to_async(_seed)()

    # A bare port name (no controller prefix) still resolves via suffix matching.
    tap_name, _, _, canonical, _ = await listener._get_tap_info("flow0")
    assert tap_name == "Main Tap"
    assert canonical == "kegboard.flow0"


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_unknown_meter_returns_nones():
    await database_sync_to_async(_seed)()

    tap_name, beer_name, beer_image_url, canonical, ticks_per_ml = (
        await listener._get_tap_info("kegboard.flowX")
    )
    assert tap_name is None
    assert beer_name is None
    assert ticks_per_ml is None


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_is_cached(monkeypatch):
    await database_sync_to_async(_seed)()

    calls = {"n": 0}
    real = listener._lookup_all

    def counting_lookup(meter_name):
        calls["n"] += 1
        return real(meter_name)

    monkeypatch.setattr(listener, "_lookup_all", counting_lookup)

    first = await listener._get_tap_info("kegboard.flow0")
    second = await listener._get_tap_info("kegboard.flow0")

    assert first == second
    assert calls["n"] == 1  # second call served from cache, no DB hit


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_db_error_returns_fallback(monkeypatch):
    def boom(meter_name):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(listener, "_lookup_all", boom)

    # A DB failure must not propagate: the loop keeps running with minimal info.
    result = await listener._get_tap_info("kegboard.flow0")
    assert result == (None, None, None, "kegboard.flow0", None)


@pytest.mark.django_db(transaction=True)
async def test_get_tap_info_db_error_serves_stale_cache(monkeypatch):
    await database_sync_to_async(_seed)()

    good = await listener._get_tap_info("kegboard.flow0")
    assert good[0] == "Main Tap"

    # Expire the cached entry so the next call attempts a fresh (failing) lookup.
    _, value = listener._tap_info_cache["kegboard.flow0"]
    listener._tap_info_cache["kegboard.flow0"] = (0.0, value)

    def boom(meter_name):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(listener, "_lookup_all", boom)

    # Lookup fails, but the last-known mapping is served instead of a blank overlay.
    stale = await listener._get_tap_info("kegboard.flow0")
    assert stale == good


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages

    async def subscribe(self, channel):
        return None

    async def listen(self):
        for message in self._messages:
            yield message


class _FakeRedis:
    def __init__(self, messages):
        self._messages = messages

    def pubsub(self):
        return _FakePubSub(self._messages)


@pytest.mark.django_db(transaction=True)
async def test_listen_broadcasts_pour_update(monkeypatch):
    await database_sync_to_async(_seed)()

    channel_layer = get_channel_layer()
    channel = await channel_layer.new_channel()
    await channel_layer.group_add(listener.WS_GROUP, channel)

    messages = [
        {
            "type": "message",
            "data": json.dumps(
                {
                    "event": "MeterUpdate",
                    "data": {"meter_name": "kegboard.flow0", "reading": 681},
                }
            ),
        },
    ]

    from redis import asyncio as redis_asyncio

    monkeypatch.setattr(
        redis_asyncio.Redis,
        "from_url",
        staticmethod(lambda *args, **kwargs: _FakeRedis(messages)),
    )

    await listener.listen("redis://unused")

    message = await channel_layer.receive(channel)
    assert message["type"] == "pour_event"
    assert message["event_type"] == "pour_update"
    assert message["tap"] == "kegboard.flow0"
    assert message["ticks"] == 681
    assert message["volume_ml"] > 0


@pytest.mark.django_db(transaction=True)
async def test_listen_ignores_non_meterupdate_events(monkeypatch):
    await database_sync_to_async(_seed)()

    channel_layer = get_channel_layer()
    channel = await channel_layer.new_channel()
    await channel_layer.group_add(listener.WS_GROUP, channel)

    messages = [
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": json.dumps({"event": "SomethingElse"})},
        {"type": "message", "data": "not-json"},
    ]

    from redis import asyncio as redis_asyncio

    monkeypatch.setattr(
        redis_asyncio.Redis,
        "from_url",
        staticmethod(lambda *args, **kwargs: _FakeRedis(messages)),
    )

    await listener.listen("redis://unused")

    # Nothing should have been broadcast. receive() blocks indefinitely on an
    # empty group, so bound it with a short timeout and assert it times out.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(channel_layer.receive(channel), timeout=1.0)
