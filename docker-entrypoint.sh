#!/bin/bash
set -e

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
while ! nc -z mysql 3306; do
  sleep 1
done
echo "MySQL is ready"

# Run migrations
echo "Running database migrations..."
kegbot migrate --noinput

# Start Daphne
echo "Starting Daphne server..."
exec daphne -b 0.0.0.0 -p 8000 pykeg.asgi:application
