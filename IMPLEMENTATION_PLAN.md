# Kegbot Fullscreen WebSocket Real-Time Pour Updates Implementation Plan

## Context
User wants WebSocket-based real-time updates on `/fullscreen` endpoint showing oz poured during active pours, with automatic return to normal view after pour completes.

## Current Architecture

### Hardware Flow Data
- **Entry Point:** `POST /api/taps/{meter_name}/` (Django REST endpoint)
- **Handler:** `/pykeg/web/api/views.py:_tap_detail_post()` (lines 661-690)
- **Data Format:** HTTP POST with `ticks`, `volume_ml`, `duration`, `username`, `tick_time_series`
- **Processing:** Calls `Drink.record_drink()` once with complete pour data

### Signal System
- `drink_recorded` signal fires after `Drink.record_drink()` completes
- Used by webhook plugin to POST events asynchronously
- Handlers in `/pykeg/core/signal_handlers.py`

### Current Frontend
- Fullscreen template: `/pykeg/web/kegweb/templates/kegweb/fullscreen.html`
- Polling-based with 10s interval + full page reload

---

## Technical Challenge: In-Progress Pour Visibility

**Current Flow:**
```
Hardware POST ticks (complete pour)
    ↓
_tap_detail_post() receives ALL ticks at once
    ↓
Drink.record_drink() creates record
    ↓
drink_recorded signal fires
    ↓
Webhook posts to external URLs
```

**Problem:** Drink data only becomes available AFTER pour completes. Cannot show real-time pour progress with current POST pattern.

**Solution:** Intercept at the POST endpoint to emit real-time tick updates BEFORE `Drink.record_drink()` completes.

---

## Implementation Strategy: Three-Phase Approach

### Phase 1: Create In-Progress Pour Tracking (Backend)

**New Model:** `PourInProgress` in `/pykeg/core/models.py`
```python
class PourInProgress(models.Model):
    keg_tap = models.ForeignKey(KegTap, on_delete=models.CASCADE)
    meter = models.ForeignKey(FlowMeter, on_delete=models.CASCADE)
    user = models.ForeignKey(User, null=True, blank=True)
    start_time = models.DateTimeField(auto_now_add=True)
    ticks = models.IntegerField(default=0)
    volume_ml = models.FloatField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    
    @property
    def is_active(self):
        # Consider inactive if no updates in 5+ seconds
        return (timezone.now() - self.last_updated).seconds < 5
```

**Modification:** Update `_tap_detail_post()` in `/pykeg/web/api/views.py`
```python
# Before: Drink.record_drink(...) 
# Add:
def _tap_detail_post(request, tap):
    # ... existing form validation ...
    
    # EMIT REAL-TIME UPDATE via Django signal BEFORE recording drink
    signals.pour_in_progress.send(
        sender=tap,
        meter_name=meter_name,
        ticks=cd["ticks"],
        volume_ml=cd.get("volume_ml"),
        duration=cd.get("duration"),
        timestamp=datetime.now(),
    )
    
    # Original drink recording (unchanged)
    drink = models.Drink.record_drink(...)
    
    # Clean up in-progress record
    PourInProgress.objects.filter(meter=meter).delete()
```

### Phase 2: WebSocket Consumer & Channels Setup

**Install django-channels:**
```bash
pip install channels channels-redis
```

**Update settings.py:**
```python
INSTALLED_APPS = [
    # ... existing apps ...
    'daphne',           # ASGI server
    'channels',         # WebSocket support
]

ASGI_APPLICATION = 'pykeg.asgi.application'

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.environ.get('REDIS_URL', 'redis://localhost:6379/0')],
        },
    }
}
```

**Create `/pykeg/asgi.py`:**
```python
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pykeg.settings')

from pykeg.web.consumers import FullscreenConsumer

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path('ws/fullscreen/', FullscreenConsumer.as_asgi()),
        ])
    ),
})
```

**Create `/pykeg/web/consumers.py`:**
```python
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.signals import Signal

pour_group_name = "fullscreen_pours"

class FullscreenConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Add this connection to broadcast group
        await self.channel_layer.group_add(pour_group_name, self.channel_name)
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(pour_group_name, self.channel_name)
    
    async def pour_event(self, event):
        # Broadcast pour updates to all connected clients
        await self.send(text_data=json.dumps({
            'type': event.get('event_type'),  # 'pour_started', 'pour_update', 'pour_ended'
            'tap': event['tap'],
            'volume_ml': event.get('volume_ml'),
            'user': event.get('user'),
            'duration_seconds': event.get('duration'),
        }))
```

**Connect Signal to WebSocket:** `/pykeg/core/signal_handlers.py`
```python
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def on_pour_in_progress(sender, meter_name, ticks, volume_ml, duration, **kwargs):
    # Broadcast to WebSocket clients
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "fullscreen_pours",
        {
            "type": "pour_event",
            "event_type": "pour_update",
            "tap": meter_name,
            "volume_ml": volume_ml,
            "duration": duration,
        }
    )

signals.pour_in_progress.connect(on_pour_in_progress)
```

### Phase 3: Frontend WebSocket Client & UI Updates

**Create `/pykeg/web/static/js/fullscreen-realtime.js`:**
```javascript
const FULLSCREEN_REALTIME_CONFIG = {
    wsUrl: (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + 
           window.location.host + '/ws/fullscreen/',
    updateTimeout: 5000  // Hide pour info after 5s of no updates
};

let currentPour = null;
let updateTimer = null;

function connectWebSocket() {
    const ws = new WebSocket(FULLSCREEN_REALTIME_CONFIG.wsUrl);
    
    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);
        
        if (data.event_type === 'pour_update') {
            currentPour = data;
            clearTimeout(updateTimer);
            updatePourDisplay(data);
            
            // Hide after timeout if no new updates
            updateTimer = setTimeout(() => {
                hidePourDisplay();
                currentPour = null;
            }, FULLSCREEN_REALTIME_CONFIG.updateTimeout);
        }
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
        // Fallback to polling if WebSocket fails
        startPollingFallback();
    };
    
    ws.onclose = function(event) {
        // Attempt reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
}

function updatePourDisplay(pourData) {
    // Find tap element and overlay pour info
    const tapElement = document.querySelector(`[data-tap="${pourData.tap}"]`);
    if (!tapElement) return;
    
    // Create or update pour overlay
    let overlay = tapElement.querySelector('.pour-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'pour-overlay';
        tapElement.appendChild(overlay);
    }
    
    // Format oz (ml / 29.5735)
    const oz = (pourData.volume_ml / 29.5735).toFixed(1);
    
    overlay.innerHTML = `
        <div class="pour-info">
            <div class="pour-title">Pouring...</div>
            <div class="pour-amount">${oz} oz</div>
            ${pourData.user ? `<div class="pour-user">${pourData.user}</div>` : ''}
        </div>
    `;
    
    overlay.style.display = 'block';
    
    // Pause carousel during pour
    if (window.slickCarousel) {
        window.slickCarousel.slick('slickPause');
    }
}

function hidePourDisplay() {
    document.querySelectorAll('.pour-overlay').forEach(el => {
        el.style.display = 'none';
    });
    
    // Resume carousel
    if (window.slickCarousel) {
        window.slickCarousel.slick('slickPlay');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', connectWebSocket);
```

**Update `/pykeg/web/kegweb/templates/kegweb/fullscreen.html`:**

Add to `<head>`:
```html
<script src="{% static 'js/fullscreen-realtime.js' %}"></script>
<style>
    .tap-display {
        position: relative;
    }
    
    .pour-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        z-index: 10;
    }
    
    .pour-info {
        text-align: center;
        color: white;
        font-size: 24px;
    }
    
    .pour-title {
        font-size: 18px;
        margin-bottom: 10px;
    }
    
    .pour-amount {
        font-size: 48px;
        font-weight: bold;
        color: #ffeb3b;
    }
    
    .pour-user {
        font-size: 14px;
        margin-top: 10px;
    }
</style>
```

Modify tap rendering:
```html
{% for tap in taps %}
    <div class="tap-display" data-tap="{{ tap.meter_name }}">
        <!-- existing tap content -->
    </div>
{% endfor %}
```

---

## Files to Create/Modify

| File | Type | Changes |
|------|------|---------|
| `/pykeg/core/models.py` | Modify | Add `PourInProgress` model, add `pour_in_progress` signal |
| `/pykeg/core/signals.py` | Modify | Define `pour_in_progress` signal |
| `/pykeg/core/signal_handlers.py` | Modify | Add WebSocket broadcast handler |
| `/pykeg/web/api/views.py` | Modify | Emit signal in `_tap_detail_post()` |
| `/pykeg/asgi.py` | Create | ASGI config for WebSocket routing |
| `/pykeg/web/consumers.py` | Create | WebSocket consumer for fullscreen |
| `/pykeg/web/static/js/fullscreen-realtime.js` | Create | Client-side WebSocket handler |
| `pykeg/settings.py` | Modify | Add channels config, ASGI app |
| `/pykeg/web/kegweb/templates/kegweb/fullscreen.html` | Modify | Add script, overlay styling, data attributes |
| `requirements.txt` or `pyproject.toml` | Modify | Add `channels`, `channels-redis` |
| `Dockerfile` | Modify | Use daphne instead of gunicorn for fullscreen |

---

## Deployment Changes

**From:** `gunicorn pykeg.web.wsgi:application --config=python:pykeg.web.gunicorn_conf`

**To:** `daphne -b 0.0.0.0 -p 8000 pykeg.asgi:application`

Or use Uvicorn as alternative ASGI server:
`uvicorn pykeg.asgi:application --host 0.0.0.0 --port 8000`

---

## Testing & Verification

**1. Database Migration:**
```bash
python manage.py makemigrations core
python manage.py migrate
```

**2. Start ASGI Server:**
```bash
daphne -b 0.0.0.0 -p 8000 pykeg.asgi:application
# Or with Uvicorn:
# uvicorn pykeg.asgi:application --reload
```

**3. Test WebSocket Connection:**
```bash
# In browser console at /fullscreen/
const ws = new WebSocket('ws://localhost:8000/ws/fullscreen/');
ws.onmessage = (event) => console.log('Received:', event.data);
```

**4. Simulate Pour:**
```bash
# In different terminal, trigger a pour via API
curl -X POST http://localhost:8000/api/taps/kegboard.flow0/ \
  -H "X-Kegbot-API-Key: YOUR_API_KEY" \
  -d "ticks=100&volume_ml=30&duration=10&username=testuser"
```

**5. Verify in Browser:**
- Open `/fullscreen/` 
- Open browser DevTools console
- Verify WebSocket connection in Network tab
- Check that WebSocket message appears when pour is triggered
- Verify pour overlay appears with oz amount

---

## Fallback Strategy

If WebSocket fails or browser doesn't support it:
- Automatically fall back to polling endpoint
- Continue showing pour updates (with slight latency)
- No user-facing error

---

## Rollback Plan

- Keep gunicorn config functional as fallback
- Polling endpoint still works for older browsers
- Django signals backward-compatible
- Can disable WebSocket in settings if needed

---

## Performance Considerations

- **Minimal overhead:** Only active pours broadcast events
- **Scalability:** Redis channel layer handles multiple connections
- **Memory:** `PourInProgress` cleaned up after pour completes
- **Latency:** WebSocket typically <100ms vs 10s polling
