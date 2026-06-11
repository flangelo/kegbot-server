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

# Install pip, Rust (for cryptography), and poetry.
# Rust install and removal are in one RUN so no Rust layer persists in the image.
RUN python -m pip install -U pip \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && PATH=/root/.cargo/bin:$PATH pip install cryptography \
    && rm -rf /root/.rustup /root/.cargo \
    && pip install poetry \
    && rm -rf /root/.cache

# Resolve and install production-only Python dependencies (no pytest, sphinx, etc.).
COPY pyproject.toml poetry.lock ./
ADD pykeg/__init__.py ./pykeg/
RUN poetry config virtualenvs.create false && poetry lock && poetry install --without dev -n

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
