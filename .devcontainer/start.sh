#!/usr/bin/env bash
# Start Afandem in the background, fully detached so it outlives this setup step.
cd "$(dirname "$0")/.."
setsid nohup python -m uv run uvicorn --factory moderator.server:create_app --host 0.0.0.0 --port 8000 \
  > /tmp/afandem.log 2>&1 < /dev/null &
for _ in $(seq 1 60); do
  curl -s -o /dev/null http://localhost:8000/api/info && { echo "Afandem is running on port 8000"; exit 0; }
  sleep 1
done
echo "Afandem did not start; see /tmp/afandem.log"
