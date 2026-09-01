#!/bin/sh
set -eu

exec uvicorn endpoint:app \
  --host 0.0.0.0 \
  --port "${ADMET_AI_PORT:-12007}"
