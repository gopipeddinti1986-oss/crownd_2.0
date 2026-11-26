#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <encrypted-backup.dump.age> <new-local-crownd_restore_test_DB>" >&2
  exit 2
fi
archive="$1"
target_db="$2"
[[ -r "$archive" ]] || { echo "Backup file is not readable" >&2; exit 1; }
# Explicit allowlist and confirmation keep this rehearsal helper from targeting a production DB.
[[ "$target_db" =~ ^crownd_restore_test_[a-z0-9_]{1,40}$ ]] || { echo "Target must start with crownd_restore_test_ and contain only lowercase letters, digits, and underscores" >&2; exit 2; }
[[ "${PGHOST:-}" == "localhost" || "${PGHOST:-}" == "127.0.0.1" || "${PGHOST:-}" == "::1" ]] || { echo "Restore rehearsal is restricted to a local PostgreSQL server (PGHOST=localhost/loopback)" >&2; exit 2; }
[[ "${CONFIRM_RESTORE_TARGET:-}" == "$target_db" ]] || { echo "Set CONFIRM_RESTORE_TARGET to exactly the new target database name" >&2; exit 2; }
: "${PGUSER:?Set PGUSER}"
: "${PGPASSFILE:?Set PGPASSFILE to a protected libpq password file}"
: "${AGE_IDENTITY_FILE:?Set AGE_IDENTITY_FILE to the protected private age identity file}"
[[ -r "$AGE_IDENTITY_FILE" ]] || { echo "AGE_IDENTITY_FILE is not readable" >&2; exit 1; }
command -v createdb >/dev/null || { echo "createdb is required" >&2; exit 1; }
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 1; }
command -v age >/dev/null || { echo "age is required" >&2; exit 1; }

createdb --host="$PGHOST" --port="${PGPORT:-5432}" --username="$PGUSER" \
  --maintenance-db="${PGMAINTENANCE_DB:-postgres}" --template=template0 "$target_db"
# Never use --clean/--create: the command only populates a newly-created, explicitly
# confirmed local rehearsal database. A failed restore leaves that isolated DB for inspection.
set -o pipefail
age --decrypt --identity "$AGE_IDENTITY_FILE" "$archive" \
  | pg_restore --exit-on-error --no-owner --no-acl --host="$PGHOST" --port="${PGPORT:-5432}" \
      --username="$PGUSER" --dbname="$target_db"
printf 'Restore rehearsal completed into local database %s; verify it, then drop it manually when finished.\n' "$target_db"
