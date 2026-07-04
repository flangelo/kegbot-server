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
TAP_INFO_TTL = 30.0  # seconds — how long to reuse a resolved meter→tap/beer mapping

# meter_name → (expiry_monotonic, resolved_tuple). The mapping barely changes
# (only on keg/tap edits), so caching it keeps the DB off the hot forwarding
# path: during a pour we resolve once per TTL instead of ~5×/sec/tap.
_tap_info_cache = {}


def _lookup_all(meter_name):
    """Resolve a raw meter name to (tap_name, beer_name, beer_image_url,
    canonical_meter_name, ticks_per_ml). Runs in a sync_to_async thread.

    The kegboard daemon sends raw device names (e.g. 'kegboard.flow0'); we
    resolve them to DB records by port suffix matching.
    """
    from django.db import close_old_connections
    from pykeg.core import models

    # This daemon holds one long-lived connection that MySQL drops after
    # wait_timeout (8h idle — i.e. overnight). Drop any stale/obsolete
    # connection first so this query always runs on a healthy one, instead of
    # stalling on a half-open socket or raising 'MySQL server has gone away'.
    close_old_connections()

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


def _reset_db_connection():
    """Force the next query to reconnect after a DB error."""
    from django.db import connection
    connection.close()


async def _get_tap_info(meter_name):
    """Cached, fault-tolerant wrapper around _lookup_all.

    Serves a cached mapping for TAP_INFO_TTL so the WebSocket forwarding loop
    doesn't touch the DB on every broadcast. A DB error never propagates: we
    drop the connection and reuse the last cached value (or a minimal fallback)
    so a stale/slow connection can neither freeze nor crash the bridge.
    """
    now = time.monotonic()
    cached = _tap_info_cache.get(meter_name)
    if cached and cached[0] > now:
        return cached[1]

    try:
        result = await sync_to_async(_lookup_all)(meter_name)
    except Exception as exc:
        # str(exc): the Redis log handler JSON-serializes log args, so a raw
        # exception object would itself raise inside this error handler.
        logger.warning("Tap lookup failed for %s (%s); using cached/fallback", meter_name, str(exc))
        await sync_to_async(_reset_db_connection)()
        if cached:
            return cached[1]  # serve stale mapping rather than a blank overlay
        return None, None, None, meter_name, None

    _tap_info_cache[meter_name] = (now + TAP_INFO_TTL, result)
    return result


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
            logger.warning("Failed to broadcast pour event: %s", str(exc))


class Command(BaseCommand):
    help = "Listen for kegnet MeterUpdate events and forward them to WebSocket clients"

    def handle(self, *args, **options):
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        logger.info("Starting kegnet listener (Redis: %s)", redis_url)
        asyncio.run(listen(redis_url))
