"""Tests for the reload_fullscreen management command."""

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management import call_command

from pykeg.core.management.commands.reload_fullscreen import WS_GROUP


@pytest.mark.django_db
def test_reload_fullscreen_broadcasts_reload_event():
    """The command should fan a reload_event out to the fullscreen group."""
    channel_layer = get_channel_layer()
    channel = async_to_sync(channel_layer.new_channel)()
    async_to_sync(channel_layer.group_add)(WS_GROUP, channel)

    call_command("reload_fullscreen")

    message = async_to_sync(channel_layer.receive)(channel)
    assert message["type"] == "reload_event"
