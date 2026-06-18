# ── Stage 1: build ────────────────────────────────────────────────────────────
# python:3.10-bullseye inherits buildpack-deps which already includes gcc,
# default-libmysqlclient-dev, libpq-dev, libffi-dev, libssl-dev, zlib1g-dev,
# curl, and other common build tools — no need to install them again.
FROM python:3.10-bullseye AS builder

RUN mkdir /app
WORKDIR /app

ENV PIP_NO_CACHE_DIR=1

# Pillow-specific build headers not covered by buildpack-deps.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
       libfreetype6-dev \
       libfribidi-dev \
       libharfbuzz-dev \
       libjpeg-dev \
       liblcms2-dev \
       libopenjp2-7-dev \
       libtiff-dev \
       libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install -U pip && pip install poetry && rm -rf /root/.cache

# Resolve and install production-only Python dependencies (no pytest, sphinx, etc.).
COPY pyproject.toml poetry.lock ./
ADD pykeg/__init__.py ./pykeg/
RUN poetry config virtualenvs.create false && poetry lock && poetry install --without dev -n

# ── Stage: test ───────────────────────────────────────────────────────────────
# Layers the dev dependencies (pytest, pytest-cov, etc.) on top of the builder so
# the suite runs against the same compiled extensions as production. This stage is
# never part of the runtime image — `docker build` defaults to the final stage, and
# docker-compose.test.yml builds it explicitly with `target: test`.
FROM builder AS test

# Install only the test tooling on top of the prod deps already present from the
# builder. We deliberately do NOT re-run `poetry install`: the builder's
# `poetry install` pinned `packaging` to the app's version, which is too old for
# poetry 2.x to run again ("No module named 'packaging.metadata'"). pip-installing
# the handful of test packages directly is both simpler and faster, and skips the
# docs/lint tooling (sphinx, black, flake8) that the suite doesn't need.
RUN pip install --no-cache-dir \
    pytest \
    pytest-django \
    pytest-cov \
    pytest-asyncio \
    requests-mock \
    vcrpy

# Application source and test data. Deps are already installed above so changes
# here don't bust the dependency layer cache.
ADD pykeg ./pykeg
ADD testdata ./testdata
COPY setup.cfg ./

ENV KEGBOT_ENV=test \
    KEGBOT_SECRET_KEY=test-secret-key \
    PYTHONDONTWRITEBYTECODE=1

# Default to the full suite with coverage; override the command to scope it down.
CMD ["pytest", "--cov=pykeg", "--cov-report=term-missing"]

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.10-slim-bullseye AS runtime

RUN mkdir /app
WORKDIR /app

ENV SHELL=/bin/sh \
    PIP_NO_CACHE_DIR=1 \
    KEGBOT_DATA_DIR=/kegbot-data \
    KEGBOT_IN_DOCKER=True \
    KEGBOT_ENV=debug

# Runtime shared libraries needed by compiled Python extensions.
# No -dev headers, no gcc, no build toolchain.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
       libffi7 \
       libfreetype6 \
       libfribidi0 \
       libharfbuzz0b \
       libjpeg62-turbo \
       liblcms2-2 \
       libopenjp2-7 \
       libtiff5 \
       libwebp6 \
       libssl1.1 \
       libmariadb3 \
       libpq5 \
       netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages and console scripts from the builder.
COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Install the application.
ADD bin /usr/local/sbin/
ADD pykeg ./pykeg

# Collect static files. Dummy env values — no real DB/Redis needed at build time.
RUN DATABASE_URL=mysql:// \
    REDIS_URL=redis:// \
    KEGBOT_SECRET_KEY=changeme \
    kegbot collectstatic --noinput -v 0

# Embed build metadata.
ARG GIT_SHORT_SHA="unknown"
ARG VERSION="unknown"
ARG BUILD_DATE="unknown"
RUN echo "GIT_SHORT_SHA=${GIT_SHORT_SHA}\nVERSION=${VERSION}\nBUILD_DATE=${BUILD_DATE}" > /etc/kegbot-version

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

VOLUME ["/kegbot-data"]
EXPOSE 8000
ENTRYPOINT ["/usr/local/sbin/kegbot"]
CMD ["run_server"]
