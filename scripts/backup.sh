#!/usr/bin/env bash
# §16 — "Daily automated Postgres backups, 30-day PITR. Restore tested
# quarterly." Production automated backups/PITR are a Railway hosting-
# platform concern, outside what this script configures — this is the
# real, working local half of that requirement: a backup+restore pair
# runnable against the docker-compose Postgres (see restore.sh), so the
# drill is a real rehearsal, not a design document.
#
# Runs pg_dump INSIDE the postgres container (docker exec), not the host's
# own pg_dump — a real run of this script surfaced a genuine version-skew
# bug: the host's Homebrew libpq (18.x) writes a dump containing
# `SET transaction_timeout = 0;`, a PG17+ GUC the docker-compose image's
# PG16 server rejects on restore. Using the container's own bundled
# pg_dump/pg_restore (always version-matched to the server, by construction)
# avoids that class of skew regardless of what happens to be on a
# developer's host — the same reason a real production backup job runs
# against the server's own version, not whatever a laptop has installed.
#
# Usage: ./scripts/backup.sh [output-directory]
set -euo pipefail

BACKUP_DIR="${1:-.docker-data/backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

PG_CONTAINER="${PG_CONTAINER:-backend-postgres-1}"
PGUSER="${PGUSER:-livestock}"
PGDATABASE="${PGDATABASE:-livestock}"

mkdir -p "$BACKUP_DIR"
OUT_FILE="$BACKUP_DIR/${PGDATABASE}_${TIMESTAMP}.dump"

echo "Backing up '$PGDATABASE' via container '$PG_CONTAINER' -> $OUT_FILE"
docker exec -i "$PG_CONTAINER" pg_dump -U "$PGUSER" -Fc "$PGDATABASE" > "$OUT_FILE"

SIZE_BYTES=$(wc -c < "$OUT_FILE" | tr -d ' ')
echo "Backup complete: $OUT_FILE ($SIZE_BYTES bytes)"
echo "$OUT_FILE"
