"""Tests for signal handlers that broadcast to fullscreen displays."""

import asyncio

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from pykeg.core import defaults, models

WS_GROUP = "fullscreen_pours"


def _receive(channel_layer, channel):
    async def receive_with_timeout():
        return await asyncio.wait_for(channel_layer.receive(channel), timeout=5)

    return async_to_sync(receive_with_timeout)()


@pytest.mark.django_db(transaction=True)
def test_keg_attach_and_end_broadcast_reload():
    """Attaching and ending a keg should each fan a reload_event out to displays."""
    defaults.set_defaults(set_is_setup=True, create_controller=True)
    channel_layer = get_channel_layer()
    channel = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(WS_GROUP, channel)

    models.Keg.start_keg(
        "kegboard.flow0",
        beverage_name="Unknown",
        producer_name="Unknown",
        beverage_type="beer",
        style_name="Unknown",
    )
    message = _receive(channel_layer, channel)
    assert message["type"] == "reload_event"

    tap = models.KegTap.get_from_meter_name("kegboard.flow0")
    tap.end_current_keg()
    message = _receive(channel_layer, channel)
    assert message["type"] == "reload_event"
