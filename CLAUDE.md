# kegbot-server — Claude Code context

## What this is
Django-based web server for Kegbot beer tap monitoring. Serves the tap list UI, REST API, admin panel, and a real-time WebSocket overlay for the fullscreen display. Three long-running processes are built from this image:
- **kegbot** (`run_server`) — Daphne ASGI server (HTTP + WebSocket) on port 8000
- **kegnet-listener** (`run_kegnet_listener`) — subscribes to Redis `kegnet` pub/sub channel and forwards `MeterUpdate` events to WebSocket clients
- **workers** (`rqworker default stats`) — RQ background workers for stats rebuilds and backups

## Development workflow
Code is written on the **MacBook** (`/Users/frodelangelo/src/kegbot-server`), then built and deployed on the **Pi** (`frode@kegberry`).

```bash
# 1. Make changes locally, commit, push
git add <files> && git commit -m "..." && git push

# 2. On the Pi: pull and build a new image
ssh kegberry "cd ~/src/kegbot-server && git pull && docker build -t ghcr.io/flangelo/kegbot-server:latest ."

# 3. Deploy (docker-compose lives in ~/kegberry on the Pi)
ssh kegberry "cd ~/kegberry && docker compose up -d kegbot kegnet-listener workers"

# 4. Check logs
ssh kegberry "docker logs kegberry-kegbot-1 --tail 50"
ssh kegberry "docker logs kegberry-kegnet-listener-1 --tail 50"
ssh kegberry "docker logs kegberry-workers-1 --tail 50"
```

## Pi directory layout
| Path | Purpose |
|------|---------|
| `~/src/kegbot-server` | this repo |
| `~/src/kegbot-pycore` | kegboard serial daemon + pycore event processor |
| `~/src/kegboard` | Arduino firmware + kegboard Python library |
| `~/kegberry/` | docker-compose deployment (`docker-compose.yml`, `nginx.conf`, `data/`) |

## Docker containers (docker-compose project: kegberry)
| Container | Image | Role |
|-----------|-------|------|
| `kegberry-kegbot-1` | `ghcr.io/flangelo/kegbot-server:latest` | Django app (Daphne ASGI) |
| `kegberry-kegnet-listener-1` | `ghcr.io/flangelo/kegbot-server:latest` | kegnet Redis → WebSocket bridge |
| `kegberry-workers-1` | `ghcr.io/flangelo/kegbot-server:latest` | RQ background workers |
| `kegberry-kegboard-1` | `kegbot/pycore:latest` | kegboard serial daemon |
| `kegberry-pycore-1` | `kegbot/pycore:latest` | pycore event processor |
| `kegberry-nginx-1` | `nginx:alpine` | reverse proxy (port 8000) |
| `kegberry-redis-1` | `redis:7.2` | message bus + task queue |
| `kegberry-mysql-1` | `mariadb:10.11` | database |

## Key environment variables
| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DATABASE_URL` | yes | `mysql://root@localhost/kegbot` | MySQL/MariaDB connection |
| `REDIS_URL` | yes | `redis://localhost:6379/0` | Redis for channel layer + RQ |
| `KEGBOT_SECRET_KEY` | yes | — | Django secret key |
| `KEGBOT_ENV` | no | `debug` | `debug`, `production`, or `test` |
| `KEGBOT_BASE_URL` | no | `""` | Canonical base URL (used for absolute links) |
| `KEGBOT_MEDIA_URL` | no | `""` | Override media URL prefix (falls back to `/media/`) |
| `KEGBOT_DATA_DIR` | no | `/kegbot-data` | Media and data storage root |
| `KEGBOT_INSECURE_SHARED_API_KEY` | no | `""` | Shared API key for pycore requests |
| `KEGBOT_IN_DOCKER` | no | `false` | Signals container context |

## Module structure
```
pykeg/
  core/          — Django models, signals, stats, RQ tasks, management commands
  api/           — Django REST Framework API (serializers, views, permissions)
  web/
    consumers.py — WebSocket consumer (FullscreenConsumer → ws/fullscreen/)
    kegweb/      — Main public UI (tap list, drink/session/keg detail pages)
    kegadmin/    — Admin UI for tap/keg management
    account/     — User account pages
    setup_wizard/— First-run setup wizard
  asgi.py        — ASGI entry point; routes HTTP→Django, WebSocket→FullscreenConsumer
  settings.py    — Django settings (do not edit; driven entirely by env vars via config.py)
  config.py      — Env var registry and validation
```

## Real-time pour overlay
`/fullscreen-realtime/` — a fullscreen tap list page with a live pour overlay.

Flow: kegboard daemon → Redis `kegnet` pub/sub → `run_kegnet_listener` → Django Channels (`fullscreen_pours` group) → WebSocket `ws/fullscreen/` → browser.

Throttled to one broadcast per 200 ms per tap (5/sec max). Meter names from the kegboard (e.g. `kegboard.flow0`) are resolved to tap/beer info by port suffix matching in the DB.

The static `/fullscreen/` endpoint shows the tap list without live updates.

## Running tests
```bash
# In the project root (requires DATABASE_URL and REDIS_URL in env, or uses test defaults)
pytest

# Run a specific test file
pytest pykeg/core/models_test.py
```

Tests use `pytest-django`. The `[tool:pytest]` config in `setup.cfg` sets `DJANGO_SETTINGS_MODULE=pykeg.settings` and reuses the DB between runs (`--reuse-db`).

## Known constraints and fixes
- **`redis-py` pinned to `<8`** — `redis-py` 8.0 sets `DEFAULT_SOCKET_TIMEOUT=5s`, which causes rqworker to crash with `redis.exceptions.TimeoutError` on idle queues. Pinned at `redis = ">=3,<8"` in `pyproject.toml`.
- **Multi-stage Dockerfile** — Stage 1 (`python:3.10-bullseye`) compiles Python extensions; Stage 2 (`python:3.10-slim-bullseye`) is the runtime image. This avoids OOM build crashes on the Pi and keeps the image slim. Do not collapse back to a single stage.
- **`KEGBOT_MEDIA_URL` for media behind a proxy** — without this set, Django's `request.build_absolute_uri` can lock `MEDIA_URL` to the first request's hostname. Set `KEGBOT_MEDIA_URL` to a host-relative path (e.g. `/media/`) or absolute URL in production to avoid broken image links.
- **Django 3.2 / Python 3.10** — upstream is pinned here. Do not upgrade Django to 4.x without auditing all custom middleware and signals; `future` package compatibility is also a constraint.

## Useful debugging
```bash
# Watch the Django app live
ssh kegberry "docker logs -f kegberry-kegbot-1"

# Watch the kegnet listener (WebSocket bridge)
ssh kegberry "docker logs -f kegberry-kegnet-listener-1"

# Check all container health
ssh kegberry "docker ps"

# Open a Django shell on the Pi
ssh kegberry "docker exec -it kegberry-kegbot-1 kegbot shell"

# Run a management command on the Pi
ssh kegberry "docker exec kegberry-kegbot-1 kegbot <command>"

# Rebuild without cache (if packages seem stale)
ssh kegberry "cd ~/src/kegbot-server && docker build --no-cache -t ghcr.io/flangelo/kegbot-server:latest ."
```
