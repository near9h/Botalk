#!/bin/sh
set -e

# Run Alembic migrations (idempotent — will create DB if missing on first run).
echo "[entrypoint] running alembic upgrade head"
alembic upgrade head || {
    echo "[entrypoint] alembic failed, attempting to stamp head and retry"
    alembic stamp head || true
}

echo "[entrypoint] launching uvicorn"
# NOTE: never enable --reload in this container. reload-mode wraps the
# app in a watchgod reloader that buffers outbound writes until 4KB
# accumulates, which breaks SSE — the browser would only see the chat
# stream after `run_end` (i.e. only on page refresh). httptools is the
# default; we pin it explicitly so a future uvicorn upgrade can't
# silently swap to h11 (which would re-introduce the buffering).
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --http httptools \
  --loop asyncio \
  --workers 1 \
  --log-level info