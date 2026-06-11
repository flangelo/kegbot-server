"""WebSocket consumers for real-time fullscreen updates."""

import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

FULLSCREEN_GROUP_NAME = "fullscreen_pours"


class FullscreenConsumer(AsyncWebsocketConsumer):
    """Broadcasts pour events to fullscreen displays via WebSocket."""

    async def connect(self):
        """Accept connection and add to broadcast group."""
        await self.channel_layer.group_add(FULLSCREEN_GROUP_NAME, self.channel_name)
        await self.accept()
        logger.debug(f"WebSocket connection established for fullscreen consumer")

    async def disconnect(self, close_code):
        """Remove from broadcast group on disconnect."""
        await self.channel_layer.group_discard(FULLSCREEN_GROUP_NAME, self.channel_name)
        logger.debug(f"WebSocket disconnected with code {close_code}")

    async def pour_event(self, event):
        """Handle pour events broadcasted to the group."""
        # Send the event data to the WebSocket client
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
