import logging
import time

from django.dispatch import receiver

from . import signals, tasks

logger = logging.getLogger(__name__)

# Throttle temperature-driven tap_state pushes to at most once per 5 minutes
# (temperature is logged every ~60s per sensor; volume is the time-sensitive field).
_TEMP_TAP_STATE_INTERVAL = 30  # seconds
_last_temp_tap_state_push = 0.0


@receiver(signals.drink_recorded)
def on_drink_recorded(sender, **kwargs):
    """Build stats when a drink is created."""
    drink = kwargs["drink"]
    tasks.build_stats.delay(drink_id=drink.id, rebuild_following=False)


@receiver(signals.drink_recorded)
def on_drink_recorded_push_tap_state(sender, **kwargs):
    """Push updated tap state (keg volume) to WebSocket clients after a pour."""
    _push_tap_state()


@receiver(signals.temperature_recorded)
def on_temperature_recorded_push_tap_state(sender, **kwargs):
    """Push updated tap state (temperature) to WebSocket clients, throttled."""
    global _last_temp_tap_state_push
    now = time.monotonic()
    if now - _last_temp_tap_state_push < _TEMP_TAP_STATE_INTERVAL:
        return
    _last_temp_tap_state_push = now
    _push_tap_state()


@receiver(signals.drink_assigned)
@receiver(signals.drink_adjusted)
@receiver(signals.drink_canceled)
def on_drink_changed(sender, **kwargs):
    """Rebuild stats when a drink is changed or (re-)assigned."""
    drink_id = kwargs["drink_id"]
    tasks.build_stats.delay(drink_id=drink_id, rebuild_following=True)


@receiver(signals.keg_deleted)
def on_keg_deleted(sender, **kwargs):
    """Rebuild stats when a keg is deleted."""
    first_deleted_drink_id = kwargs["first_deleted_drink_id"]
    if first_deleted_drink_id:
        tasks.build_stats.delay(drink_id=first_deleted_drink_id, rebuild_following=True)


@receiver(signals.events_created)
def on_events_created(sender, **kwargs):
    """Send events to plugins."""
    events = kwargs["events"]
    tasks.schedule_tasks(events)


@receiver(signals.pour_in_progress)
def on_pour_in_progress(sender, **kwargs):
    """Broadcast pour_ended event to WebSocket clients."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            "fullscreen_pours",
            {
                "type": "pour_event",
                "event_type": "pour_ended",
                "tap": kwargs.get("meter_name"),
                "tap_name": kwargs.get("tap_name"),
                "beer_name": kwargs.get("beer_name"),
                "beer_image_url": kwargs.get("beer_image_url"),
                "volume_ml": kwargs.get("volume_ml", 0),
                "user": str(kwargs["user"]) if kwargs.get("user") else None,
                "duration_seconds": kwargs.get("duration", 0),
                "ticks": kwargs.get("ticks", 0),
            },
        )
    except Exception as exc:
        logger.warning("Failed to broadcast pour_ended event: %s", exc)


def _push_tap_state():
    """Push current tap state (volume, temperature, illustration) to WebSocket clients."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        from pykeg.web.consumers import build_tap_state_payload

        taps = build_tap_state_payload()
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "fullscreen_pours",
            {"type": "tap_state_event", "taps": taps},
        )
    except Exception as exc:
        logger.warning("Failed to broadcast tap_state: %s", exc)
