# Real-Time Pour Overlay for the Fullscreen Endpoint

## Overview

The `/fullscreen` page now shows a live pour overlay whenever a keg is being tapped. The overlay stacks cards for all active pours (first-started on top), updates the poured volume in real time, and disappears automatically 10 seconds after the last update. The carousel pauses while any pour is active and resumes once all cards have been dismissed.

Two event sources are supported:

| Source | Path |
|--------|------|
| HTTP API (`POST /api/taps/<meter>/`) | `views.py` → `pour_in_progress` signal → signal handler → channel layer |
| Real kegboard hardware via pycore | `kegnet` Redis pub/sub → `run_kegnet_listener` management command → channel layer |

Both paths converge on the same Django Channels group (`fullscreen_pours`) and the same WebSocket consumer, so the browser sees identical events regardless of source.

---

## Architecture

```
kegboard / pycore
    │  publishes FlowUpdate to Redis "kegnet" channel
    ▼
run_kegnet_listener (management command)
    │  subscribes, translates FlowUpdate → channel layer group_send
    ▼
Django Channels channel layer  (Redis-backed)
    │
    ├── HTTP pour (POST /api/taps/…)
    │       views.py fires pour_in_progress signal
    │       signal_handlers.py → channel layer group_send
    │
    ▼
FullscreenConsumer (WebSocket)
    │  relays event as JSON to every connected browser
    ▼
fullscreen-realtime.js
    │  maintains pourOrder[] + currentPours{}
    ▼
#pour-panel  (stacked cards, fixed center overlay)
```

---

## New Dependencies

Added to `pyproject.toml`:

| Package | Purpose |
|---------|---------|
| `daphne ^4.0.0` | ASGI server (replaces gunicorn) |
| `channels ^4.0.0` | Django Channels (WebSocket support) |
| `channels-redis ^4.1.0` | Redis channel layer backend |
| `uvicorn ^0.24.0` | ASGI runner (optional, Daphne is primary) |

---

## New Files

### `pykeg/asgi.py`

ASGI application entry point. Routes HTTP traffic to the standard Django app and WebSocket traffic to `FullscreenConsumer`.

```python
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter([
        path("ws/fullscreen/", FullscreenConsumer.as_asgi()),
    ])),
})
```

### `pykeg/web/consumers.py`

`FullscreenConsumer` — an `AsyncWebsocketConsumer` that:

- Joins the `fullscreen_pours` channel group on connect.
- Leaves the group on disconnect.
- Forwards any `pour_event` group message to the browser as JSON, including: `event_type`, `tap`, `tap_name`, `beer_name`, `beer_image_url`, `volume_ml`, `ticks`, `user`, `duration_seconds`.

### `pykeg/web/static/js/fullscreen-realtime.js`

Client-side WebSocket handler. Key data structures:

```
currentPours  {}   — tapName → latest pourData
pourOrder     []   — tapNames in start order (index 0 = first-started = top of stack)
updateTimers  {}   — tapName → setTimeout id
```

Lifecycle:

1. `handlePourUpdate(data)` — adds tap to `pourOrder` if new, updates `currentPours`, resets the 10-second idle timer, calls `renderPourPanel()`.
2. `handlePourEnded(data)` — cancels timer, removes tap from both structures, calls `renderPourPanel()`.
3. `removePour(tapName)` — called by either the `pour_ended` event or the idle timeout.
4. `renderPourPanel()` — rebuilds `#pour-panel` from `pourOrder` on every change. Shows/hides the panel and pauses/resumes the Slick carousel.

Reconnects automatically after a 3-second delay if the WebSocket closes.

### `pykeg/core/management/commands/run_kegnet_listener.py`

Django management command (`kegbot run_kegnet_listener`) that bridges pycore's Redis pub/sub into the channel layer.

- Subscribes to the `kegnet` Redis channel.
- Filters for `FlowUpdate` messages.
- Resolves `meter_name` to a `KegTap` using `FlowMeter.get_from_meter_name()`, with a port-suffix fallback for names that differ between pycore and the database.
- All DB access is wrapped in a single `sync_to_async` block using `select_related` to avoid async-context errors.
- Emits `pour_update` (state `ACTIVE`/`IDLE`) or `pour_ended` (state `COMPLETED`) to `fullscreen_pours`.
- Beer image URL is built as `MEDIA_URL + pic.image.name` (a relative path) because the management command runs outside a request context and cannot use `kbstorage.url()`.

### `docker-entrypoint.sh`

Startup script for the `kegbot` container:

1. Waits for MySQL to accept connections (`nc -z mysql 3306`).
2. Runs `kegbot migrate --noinput`.
3. Starts `daphne -b 0.0.0.0 -p 8000 pykeg.asgi:application`.

---

## Modified Files

### `pykeg/settings.py`

- Added `daphne` and `channels` to `INSTALLED_APPS`.
- Set `ASGI_APPLICATION = "pykeg.asgi.application"`.
- Added `CHANNEL_LAYERS` config:

```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            # redis-py 8.0 introduced DEFAULT_SOCKET_TIMEOUT=5s, which races
            # channels_redis's 5s BRPOP timeout and raises TimeoutError instead
            # of returning None. Explicitly set None to restore old behaviour.
            "hosts": [{"address": KEGBOT["REDIS_URL"], "socket_timeout": None}],
        },
    },
}
```

> **Note:** The `socket_timeout: None` override is required. redis-py 8.0 introduced a default 5-second socket timeout that races with channels_redis's internal 5-second `BRPOP` timeout, causing spurious `TimeoutError` exceptions and rapid WebSocket connect/disconnect cycling.

### `pykeg/core/signals.py`

Added:

```python
pour_in_progress = Signal()
```

### `pykeg/core/signal_handlers.py`

Added `on_pour_in_progress` receiver. Fired by `views.py` when an HTTP pour is recorded. Calls `channel_layer.group_send` synchronously via `async_to_sync`.

### `pykeg/web/api/views.py`

In the tap recording view, before writing the drink to the database:

1. Resolves the current `FlowMeter` and calls `meter.meter_name()`.
2. Looks up the current keg's beer name and image URL (`keg.type.picture.resized.url`, with `get_illustration_thumb()` as fallback; both wrapped in `try/except`).
3. Fires `signals.pour_in_progress.send(...)` with all resolved fields.

### `pykeg/web/kegweb/templates/kegweb/fullscreen.html`

- Added CSS for `#pour-panel` (fixed, centered, `flex-column` container) and `.pour-card` / `.pour-card-image` / `.pour-card-info` (individual pour entries).
- Added `<div id="pour-panel"></div>` at the bottom of the body, outside the carousel.
- Added `<script>` tag for `fullscreen-realtime.js`.
- Stores the Slick carousel reference as `window.slickCarousel` so the JS can pause/resume it.
- The polling fallback (`fetchEvents`) only triggers a full page reload when the WebSocket is not connected (`window.wsConnection.readyState !== WebSocket.OPEN`).
- Each `.tap-display` element carries `data-tap` and `data-meter-name` attributes set to `{{ tap.meter }}` (the `FlowMeter.__str__` value, e.g. `"Main tap.flow0"`).

### `docker-compose.yml`

- `kegbot` service: replaced default command with `entrypoint: /docker-entrypoint.sh` (runs Daphne instead of gunicorn).
- Added `kegnet-listener` service that runs `run_kegnet_listener` for real-hardware support.

### `Dockerfile`

- Added `netcat-openbsd` to the apt install list (used by `docker-entrypoint.sh` for the MySQL readiness check).
- Copies and chmod's `docker-entrypoint.sh`.

---

## Pour Card Layout

When one or more kegs are being poured the panel appears centred on screen:

```
┌─────────────────────────────────────────┐
│ [label] Secondary tap                   │  ← first pour (oldest, on top)
│         Summer Ale                      │
│         Pouring…             12.0 oz    │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│         Main tap                        │  ← second pour (started later)
│         African Amber                   │
│         Pouring…              8.5 oz    │
└─────────────────────────────────────────┘
```

- Cards are added at the **bottom** as new pours start.
- A card is removed when the keg finishes (`pour_ended` event) or after **10 seconds** of no updates.
- When the last card is removed the carousel resumes.

---

## Known Limitations

- **Beer image in kegnet listener path**: uses the original uploaded image (`MEDIA_URL + pic.image.name`) rather than the `resized` ImageKit spec, because the management command runs outside a Django request context and cannot resolve the storage URL. The CSS (`max-height: 100px; object-fit: contain`) handles display sizing.
- **No authentication on the WebSocket endpoint**: `AuthMiddlewareStack` is applied but the consumer does not enforce login. Acceptable for a local network deployment.
