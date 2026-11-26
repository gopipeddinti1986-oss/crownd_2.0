#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${PGHOST:?Set PGHOST}"
: "${PGUSER:?Set PGUSER}"
: "${PGDATABASE:?Set PGDATABASE}"
: "${AGE_RECIPIENT:?Set AGE_RECIPIENT to the public age recipient key}"
: "${PGPASSFILE:?Set PGPASSFILE to a protected libpq password file}"
command -v pg_dump >/dev/null || { echo "pg_dump is required" >&2; exit 1; }
command -v age >/dev/null || { echo "age is required; refusing to create an unencrypted backup" >&2; exit 1; }

backup_dir="${BACKUP_DIR:-./backups}"
keep_days="${BACKUP_KEEP_DAYS:-30}"
[[ "$keep_days" =~ ^[1-9][0-9]{0,3}$ ]] || { echo "BACKUP_KEEP_DAYS must be a positive integer" >&2; exit 2; }
mkdir -p -- "$backup_dir"
chmod 700 -- "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$backup_dir/crownd-$stamp.dump.age"
temporary="$backup_dir/.crownd-$stamp.dump.age.tmp.$$"
[[ ! -e "$output" ]] || { echo "Refusing to overwrite an existing backup" >&2; exit 1; }
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM

pg_dump --format=custom --no-owner --no-acl \
  --host="$PGHOST" --port="${PGPORT:-5432}" --username="$PGUSER" --dbname="$PGDATABASE" \
  | age --encrypt --recipient "$AGE_RECIPIENT" --output "$temporary"
chmod 600 -- "$temporary"
mv -- "$temporary" "$output"
find "$backup_dir" -maxdepth 1 -type f -name 'crownd-*.dump.age' -mtime "+$keep_days" -delete
printf 'Encrypted backup created: %s\n' "$output"
