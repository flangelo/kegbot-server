"""Broadcast a reload command to all connected fullscreen WebSocket clients.

Used to push new static assets (JS/CSS/templates) to live displays without
waiting for their periodic auto-reload. Sends a 'reload' event over the
'fullscreen_pours' channel group, which FullscreenConsumer forwards to the
browser, triggering location.reload().
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand

WS_GROUP = "fullscreen_pours"


class Command(BaseCommand):
    help = "Tell all connected fullscreen displays to reload the page."

    def handle(self, *args, **options):
        channel_layer = get_channel_layer()
        if channel_layer is None:
            self.stderr.write("No channel layer configured; cannot broadcast reload.")
            return

        async_to_sync(channel_layer.group_send)(
            WS_GROUP, {"type": "reload_event"}
        )
        self.stdout.write("Sent reload to fullscreen displays.")
