#!/usr/bin/env bash
# Bulk-loads a generated claims.csv into Postgres via COPY (tools/load_bulk.sql),
# then calls POST /api/entities/resolve-backlog so the loaded claims get
# entity links exactly the way an API-submitted claim would. This is the
# 50k-scale path from docs/EXECUTION_PLAN.md M4 - the backend must
# already be running (`make up && make run`) before you call this.
set -euo pipefail

CSV_PATH="${1:-data/claims.csv}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5434}"
DB_NAME="${DB_NAME:-claimguard}"
DB_USER="${DB_USER:-claimguard}"
API_BASE_URL="${API_BASE_URL:-http://localhost:8080}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ABS_CSV_PATH="$(cd "$(dirname "$CSV_PATH")" && pwd)/$(basename "$CSV_PATH")"

RENDERED_SQL="$(mktemp)"
trap 'rm -f "$RENDERED_SQL"' EXIT
sed "s#__CSV_PATH__#$ABS_CSV_PATH#" "$SCRIPT_DIR/load_bulk.sql" > "$RENDERED_SQL"

echo "Loading $CSV_PATH into $DB_NAME via COPY..."
PGPASSWORD="${PGPASSWORD:-claimguard_dev_password}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f "$RENDERED_SQL"

echo "Triggering entity-resolution backlog pass..."
curl -s -X POST "$API_BASE_URL/api/entities/resolve-backlog"
echo
