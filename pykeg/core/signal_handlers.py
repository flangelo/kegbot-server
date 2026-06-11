from django.dispatch import receiver

from . import signals, tasks


@receiver(signals.drink_recorded)
def on_drink_recorded(sender, **kwargs):
    """Build stats when a drink is created."""
    drink = kwargs["drink"]
    tasks.build_stats.delay(drink_id=drink.id, rebuild_following=False)


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
    """Broadcast pour updates to WebSocket clients."""
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
    except Exception as e:
        # Log error but don't break the drink recording if WebSocket fails
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to broadcast pour event: {e}")

