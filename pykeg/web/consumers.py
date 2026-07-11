"""WebSocket consumers for real-time fullscreen updates."""

import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

FULLSCREEN_GROUP_NAME = "fullscreen_pours"


def build_tap_state_payload():
    """Return a list of per-tap state dicts suitable for a tap_state WebSocket message.

    Mirrors jquery.autounits.js and the temperature/volume template tag formatting
    so the browser can update DOM elements in place without a page reload.

    Call via sync_to_async() from async contexts.
    """
    import urllib.parse

    from django.conf import settings

    from pykeg.core import models
    from pykeg.core.util import CtoF

    kbsite = models.KegbotSite.get()
    metric = kbsite.volume_display_units == "metric"
    use_f = kbsite.temperature_display_units == "f"

    taps = models.KegTap.objects.filter(current_keg__isnull=False).select_related(
        "current_keg", "temperature_sensor"
    )

    result = []
    for tap in taps:
        keg = tap.current_keg
        if not keg:
            continue

        volume_ml = max(0.0, keg.remaining_volume_ml())
        volume_label = _format_volume(volume_ml, metric)

        # Build illustration URL directly from STATIC_URL — keg.get_illustration()
        # calls KegbotSite.full_url() which requires an HTTP request context.
        pct = keg.percent_full()
        if pct >= 98.0:
            level = 5
        elif pct >= 75.0:
            level = 4
        elif pct >= 45.0:
            level = 3
        elif pct >= 25.0:
            level = 2
        elif pct >= 10.0:
            level = 1
        else:
            level = 0
        illustration_url = urllib.parse.urljoin(
            settings.STATIC_URL, f"images/keg/full/keg-srm14-{level}.png"
        )

        temp_str = None
        temp_rec = tap.Temperature()
        if temp_rec is not None:
            val = CtoF(temp_rec.temp) if use_f else temp_rec.temp
            unit = "F" if use_f else "C"
            temp_str = f"{round(val, 1)}° {unit}"

        result.append(
            {
                "tap_id": tap.id,
                "volume_label": volume_label,
                "illustration_url": illustration_url,
                "temp_str": temp_str,
                "low_status": keg.level_status(),  # None | "low" | "critical"
            }
        )

    return result


def _format_volume(volume_ml, metric=False):
    """Mirror jquery.autounits.js toHuman() so formatted strings match the page."""
    if not metric:
        oz = volume_ml * 0.0338140227
        if oz < 10:
            return f"{oz:.2f} oz"
        elif oz < 128:
            return f"{oz:.1f} oz"
        else:
            return f"{oz / 16:.0f} pints"
    else:
        liters = volume_ml / 1000.0
        if liters < 0.5:
            return f"{liters:.2f} L"
        elif liters < 100:
            return f"{liters:.1f} L"
        else:
            return f"{liters:.0f} L"


class FullscreenConsumer(AsyncWebsocketConsumer):
    """Broadcasts pour events and tap state to fullscreen displays via WebSocket."""

    async def connect(self):
        """Accept connection, join broadcast group, and send current tap state."""
        await self.channel_layer.group_add(FULLSCREEN_GROUP_NAME, self.channel_name)
        await self.accept()
        tap_state = await sync_to_async(build_tap_state_payload)()
        await self.send(
            text_data=json.dumps({"event_type": "tap_state", "taps": tap_state})
        )
        logger.debug("WebSocket connected, sent initial tap_state (%d taps)", len(tap_state))

    async def disconnect(self, close_code):
        """Remove from broadcast group on disconnect."""
        await self.channel_layer.group_discard(FULLSCREEN_GROUP_NAME, self.channel_name)
        logger.debug("WebSocket disconnected with code %s", close_code)

    async def pour_event(self, event):
        """Forward pour_update / pour_ended events to the WebSocket client."""
        await self.send(
            text_data=json.dumps(
                {
                    "event_type": event.get("event_type"),
                    "tap": event.get("tap"),
                    "tap_name": event.get("tap_name"),
                    "beer_name": event.get("beer_name"),
                    "beer_image_url": event.get("beer_image_url"),
                    "volume_ml": event.get("volume_ml"),
                    "user": event.get("user"),
                    "duration_seconds": event.get("duration_seconds"),
                    "ticks": event.get("ticks"),
                }
            )
        )

    async def tap_state_event(self, event):
        """Forward tap_state updates (volume, temperature, illustration) to the client."""
        await self.send(
            text_data=json.dumps(
                {"event_type": "tap_state", "taps": event.get("taps", [])}
            )
        )

    async def reload_event(self, event):
        """Tell the client to reload the page (e.g. to pick up new static assets)."""
        await self.send(text_data=json.dumps({"event_type": "reload"}))
