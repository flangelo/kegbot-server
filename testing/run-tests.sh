#!/usr/bin/env bash
# Run the test suite inside the containerized test stack (MariaDB + Redis + app).
#
# Usage:
#   testing/run-tests.sh                       # full suite with coverage
#   testing/run-tests.sh pykeg/core/models_test.py   # a single file
#   testing/run-tests.sh -k FullscreenConsumer       # pytest expression
#
# Any arguments are passed straight to pytest. Works on the MacBook and the Pi;
# no host Python required.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.test.yml"

cleanup() {
  $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ $# -eq 0 ]]; then
  $COMPOSE run --rm --build test
else
  $COMPOSE run --rm --build test pytest "$@"
fi
