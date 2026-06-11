"""Subscribe to the kegnet Redis pub/sub channel and broadcast pour events
to WebSocket clients via the channel layer.

The kegboard daemon publishes MeterUpdate messages to 'kegnet' in real-time
as the user pours.  This command bridges those events into the fullscreen
WebSocket pipeline so the browser overlay updates incrementally.
"""

import asyncio
import json
import logging
import os
import time

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

KEGNET_CHANNEL = "kegnet"
WS_GROUP = "fullscreen_pours"
BROADCAST_INTERVAL = 0.2  # seconds — max 5 WebSocket pushes per tap per second


async def _get_tap_info(meter_name):
    """Return (tap_name, beer_name, beer_image_url, canonical_meter_name, ticks_per_ml).

    The kegboard daemon sends raw device names (e.g. 'kegboard.flow0').
    We resolve these to database records by port suffix matching.
    All DB access is kept inside a single sync_to_async block.
    """
    from pykeg.core import models

    def _lookup_all():
        # 1. Exact match.
        try:
            meter = models.FlowMeter.get_from_meter_name(meter_name)
        except (models.FlowMeter.DoesNotExist, Exception):
            meter = None

        # 2. Fall back to matching on port suffix (e.g. "kegboard.flow0" → "flow0").
        if meter is None:
            port_name = meter_name.rsplit(".", 1)[-1] if "." in meter_name else meter_name
            meter = models.FlowMeter.objects.select_related(
                "controller", "tap", "tap__current_keg", "tap__current_keg__type"
            ).filter(port_name=port_name).first()
        else:
            meter = models.FlowMeter.objects.select_related(
                "controller", "tap", "tap__current_keg", "tap__current_keg__type"
            ).get(pk=meter.pk)

        if meter is None:
            return None, None, None, meter_name, None

        canonical = meter.meter_name()
        ticks_per_ml = meter.ticks_per_ml

        try:
            tap = meter.tap
        except Exception:
            return None, None, None, canonical, ticks_per_ml
        if not tap:
            return None, None, None, canonical, ticks_per_ml

        keg = tap.current_keg
        beer = None
        beer_image_url = None
        if keg and keg.type:
            beer = keg.type.name
            pic = getattr(keg.type, "picture", None)
            if pic and pic.image:
                from django.conf import settings
                media_url = getattr(settings, "MEDIA_URL", "/media/")
                beer_image_url = media_url.rstrip("/") + "/" + pic.image.name
        return tap.name, beer, beer_image_url, canonical, ticks_per_ml

    return await sync_to_async(_lookup_all)()


async def listen(redis_url):
    from channels.layers import get_channel_layer
    from redis.asyncio import Redis

    channel_layer = get_channel_layer()
    redis = Redis.from_url(redis_url, socket_timeout=None)
    pubsub = redis.pubsub()
    await pubsub.subscribe(KEGNET_CHANNEL)
    logger.info("Subscribed to '%s', forwarding MeterUpdate → WebSocket", KEGNET_CHANNEL)

    last_broadcast = {}  # meter_name → time.monotonic() of last group_send

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        try:
            payload = json.loads(message["data"])
        except (json.JSONDecodeError, TypeError):
            continue

        if payload.get("event") != "MeterUpdate":
            continue

        data = payload.get("data", {})
        meter_name = data.get("meter_name", "")
        ticks = data.get("reading", 0)

        # Throttle to BROADCAST_INTERVAL per tap — skip DB lookup and send entirely.
        now = time.monotonic()
        if now - last_broadcast.get(meter_name, 0) < BROADCAST_INTERVAL:
            continue

        tap_name, beer_name, beer_image_url, canonical_meter, ticks_per_ml = \
            await _get_tap_info(meter_name)

        volume_ml = (ticks / ticks_per_ml) if ticks_per_ml else 0

        try:
            await channel_layer.group_send(
                WS_GROUP,
                {
                    "type": "pour_event",
                    "event_type": "pour_update",
                    "tap": canonical_meter,
                    "tap_name": tap_name,
                    "beer_name": beer_name,
                    "beer_image_url": beer_image_url,
                    "volume_ml": volume_ml,
                    "ticks": ticks,
                    "user": None,
                },
            )
            last_broadcast[meter_name] = now
            logger.debug(
                "Broadcast pour_update for %s: %.1f ml (%d ticks)",
                canonical_meter, volume_ml, ticks,
            )
        except Exception as exc:
            logger.warning("Failed to broadcast pour event: %s", exc)


class Command(BaseCommand):
    help = "Listen for kegnet MeterUpdate events and forward them to WebSocket clients"

    def handle(self, *args, **options):
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        logger.info("Starting kegnet listener (Redis: %s)", redis_url)
        asyncio.run(listen(redis_url))
