"""Tests for the real-time fullscreen WebSocket consumer.

Covers three layers:
  * ``_format_volume`` — pure formatting, no DB.
  * ``build_tap_state_payload`` — DB-backed per-tap state assembly.
  * ``FullscreenConsumer`` — connect/broadcast behaviour over the channel layer.

The async tests use the configured channel layer (Redis in the test stack) and
seed the DB via ``database_sync_to_async`` with ``transaction=True`` so the
committed rows are visible to the consumer's worker thread.
"""

import pytest
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator

from pykeg.core import models
from pykeg.test import factories
from pykeg.web.consumers import (
    FULLSCREEN_GROUP_NAME,
    FullscreenConsumer,
    _format_volume,
    build_tap_state_payload,
)


class TestFormatVolume:
    """Pure-function formatting; mirrors jquery.autounits.js toHuman()."""

    def test_imperial_small_uses_two_decimals(self):
        # 100 ml ≈ 3.38 oz, under the 10 oz threshold.
        assert _format_volume(100) == "3.38 oz"

    def test_imperial_medium_uses_one_decimal(self):
        # 1000 ml ≈ 33.8 oz, between 10 and 128 oz.
        assert _format_volume(1000) == "33.8 oz"

    def test_imperial_large_switches_to_pints(self):
        # 5000 ml ≈ 169 oz, over 128 oz → pints.
        assert _format_volume(5000).endswith("pints")

    def test_metric_small_uses_two_decimals(self):
        assert _format_volume(100, metric=True) == "0.10 L"

    def test_metric_medium_uses_one_decimal(self):
        assert _format_volume(1500, metric=True) == "1.5 L"


@pytest.mark.django_db
class TestBuildTapStatePayload:
    def _setup_site(self):
        factories.create_site()
        factories.start_keg("kegboard.flow0")

    def test_only_taps_with_a_keg_are_included(self):
        self._setup_site()
        # flow0 has a keg; flow1 ("Second Tap") does not.
        payload = build_tap_state_payload()
        assert len(payload) == 1
        tap = models.KegTap.objects.get(name="Main Tap")
        assert payload[0]["tap_id"] == tap.id

    def test_empty_when_no_kegs(self):
        factories.create_site()
        assert build_tap_state_payload() == []

    def test_imperial_volume_and_fahrenheit_temp(self):
        self._setup_site()
        tap = models.KegTap.objects.get(name="Main Tap")
        factories.attach_temp_sensor(tap, temp_c=4.0)

        entry = build_tap_state_payload()[0]
        # Default site units are imperial / Fahrenheit.
        assert entry["volume_label"].endswith("oz") or entry["volume_label"].endswith(
            "pints"
        )
        # 4.0 C == 39.2 F.
        assert entry["temp_str"] == "39.2° F"
        # A freshly started keg is full → highest illustration level.
        assert entry["illustration_url"].endswith("keg-srm14-5.png")

    def test_metric_celsius_formatting(self):
        self._setup_site()
        site = models.KegbotSite.get()
        site.volume_display_units = "metric"
        site.temperature_display_units = "c"
        site.save()
        tap = models.KegTap.objects.get(name="Main Tap")
        factories.attach_temp_sensor(tap, temp_c=4.0)

        entry = build_tap_state_payload()[0]
        assert entry["volume_label"].endswith("L")
        assert entry["temp_str"] == "4.0° C"

    def test_no_temp_sensor_yields_none(self):
        self._setup_site()
        entry = build_tap_state_payload()[0]
        assert entry["temp_str"] is None


def _seed_site_with_keg():
    factories.create_site()
    factories.start_keg("kegboard.flow0")


@pytest.mark.django_db(transaction=True)
async def test_consumer_connect_sends_initial_tap_state():
    await database_sync_to_async(_seed_site_with_keg)()

    communicator = WebsocketCommunicator(
        FullscreenConsumer.as_asgi(), "/ws/fullscreen/"
    )
    connected, _ = await communicator.connect()
    assert connected

    message = await communicator.receive_json_from()
    assert message["event_type"] == "tap_state"
    assert len(message["taps"]) == 1

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_consumer_forwards_group_pour_event():
    await database_sync_to_async(_seed_site_with_keg)()

    communicator = WebsocketCommunicator(
        FullscreenConsumer.as_asgi(), "/ws/fullscreen/"
    )
    connected, _ = await communicator.connect()
    assert connected
    # Drain the initial tap_state push.
    await communicator.receive_json_from()

    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        FULLSCREEN_GROUP_NAME,
        {
            "type": "pour_event",
            "event_type": "pour_update",
            "tap": "kegboard.flow0",
            "tap_name": "Main Tap",
            "beer_name": "Test Lager",
            "beer_image_url": None,
            "volume_ml": 250.0,
            "ticks": 681,
            "user": None,
        },
    )

    message = await communicator.receive_json_from()
    assert message["event_type"] == "pour_update"
    assert message["tap"] == "kegboard.flow0"
    assert message["volume_ml"] == 250.0

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_consumer_forwards_reload_event():
    await database_sync_to_async(_seed_site_with_keg)()

    communicator = WebsocketCommunicator(
        FullscreenConsumer.as_asgi(), "/ws/fullscreen/"
    )
    connected, _ = await communicator.connect()
    assert connected
    await communicator.receive_json_from()  # initial tap_state

    channel_layer = get_channel_layer()
    await channel_layer.group_send(FULLSCREEN_GROUP_NAME, {"type": "reload_event"})

    message = await communicator.receive_json_from()
    assert message == {"event_type": "reload"}

    await communicator.disconnect()
