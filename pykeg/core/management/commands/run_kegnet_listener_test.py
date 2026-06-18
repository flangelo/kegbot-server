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
