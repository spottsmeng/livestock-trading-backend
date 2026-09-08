#!/usr/bin/env bash
# Restores a backup.sh dump into a SCRATCH database — never the real dev DB
# — so the drill proves the backup is actually usable without risking the
# database anyone is actively developing against. Drops and recreates the
# scratch database each run, so the drill is repeatable. Runs createdb/
# dropdb/pg_restore inside the postgres container itself — see backup.sh's
# comment for why (version-matched client tools, not the host's).
#
# Usage: ./scripts/restore.sh <dump-file> [scratch-db-name]
set -euo pipefail

DUMP_FILE="${1:?Usage: restore.sh <dump-file> [scratch-db-name]}"
SCRATCH_DB="${2:-livestock_restore_drill}"

PG_CONTAINER="${PG_CONTAINER:-backend-postgres-1}"
PGUSER="${PGUSER:-livestock}"

echo "Recreating scratch database '$SCRATCH_DB'..."
docker exec -i "$PG_CONTAINER" dropdb -U "$PGUSER" --if-exists "$SCRATCH_DB"
docker exec -i "$PG_CONTAINER" createdb -U "$PGUSER" "$SCRATCH_DB"

echo "Restoring $DUMP_FILE -> $SCRATCH_DB..."
docker exec -i "$PG_CONTAINER" pg_restore -U "$PGUSER" -d "$SCRATCH_DB" --no-owner --no-privileges < "$DUMP_FILE"

echo "Restore complete into '$SCRATCH_DB'."
echo "$SCRATCH_DB"
