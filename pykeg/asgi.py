"""ASGI config for Kegbot with WebSocket support for real-time updates."""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pykeg.settings")

django_asgi_app = get_asgi_application()

from pykeg.web.consumers import FullscreenConsumer

websocket_urlpatterns = [
    path("ws/fullscreen/", FullscreenConsumer.as_asgi()),
]

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
