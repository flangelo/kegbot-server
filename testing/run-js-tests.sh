#!/usr/bin/env bash
# Run the frontend (browser JS) unit tests in a Node container. No host Node
# required. Any arguments are passed through to `npm test` (vitest).
#
#   testing/run-js-tests.sh
#   testing/run-js-tests.sh -- -t handlePourUpdate
set -euo pipefail

cd "$(dirname "$0")/.."

docker run --rm -v "$(pwd):/app" -w /app node:20-slim \
  sh -c "npm ci --no-audit --no-fund --loglevel=error && npm test ${*:-}"
