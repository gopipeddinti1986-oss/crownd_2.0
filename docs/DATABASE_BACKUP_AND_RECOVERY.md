# PostgreSQL backup and recovery

This is an operator runbook, not evidence that a backup provider or restore has been configured. Phase 10 added local helper scripts; their external tools (`pg_dump`, `pg_restore`, `createdb`, `age`) and a PostgreSQL server are not installed in the current environment, so backup/restore was **not executed**. Test the full process against a disposable non-production database before adopting it.

## Policy to establish before launch

- **Frequency:** at least daily encrypted full logical backups; increase frequency to meet the business-approved recovery point objective. This repository does not define an RPO/RTO.
- **Retention:** `scripts/backup_postgres.sh` defaults to deleting its own encrypted backup files older than 30 days in the selected directory. Set `BACKUP_KEEP_DAYS` only after retention approval. Keep copies in a separate failure domain; a local folder or the same database provider is not sufficient by itself.
- **Encryption:** the script streams a custom-format `pg_dump` through `age` directly to a `.dump.age` file, so it does not write an unencrypted intermediate dump. Store the age identity/private key separately in a secret manager/offline recovery location; backups use the public recipient key. Restrict directory/file permissions. Protect off-site transport and storage and test recovery of the identity.
- **Credentials:** libpq reads credentials from `PGPASSFILE`, not command arguments. Keep that file mode `0600`, outside Git and outside backup artifacts. Never paste secrets into shell history or support logs.
- **Monitoring:** alert on the scheduled job's nonzero exit, stale/missing backup timestamp, unexpectedly small backup, and failure to decrypt/restore in scheduled rehearsal. A script's success message alone is not restore proof.
- **Restore rehearsal:** at least quarterly and after material migration/provider changes, decrypt and restore to an isolated non-production PostgreSQL database; verify the Alembic revision, foreign keys, representative account/order/reward/ledger/notification queries, and application readiness. Record elapsed restore time and any data loss window.

## Create an encrypted backup

Requirements: PostgreSQL client tools matching the deployed server major version, `age`, an `AGE_RECIPIENT` public key, and protected `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSFILE` variables. `PGPASSFILE` format is libpq's `host:port:database:user:password` with special characters escaped per libpq rules.

```sh
install -d -m 700 "$HOME/crownd-backups"
export PGHOST='db-host.example'
export PGPORT='5432'
export PGUSER='crownd_backup'
export PGDATABASE='crownd'
export PGPASSFILE="$HOME/.pgpass-crownd-backup" # create securely, chmod 600
export AGE_RECIPIENT='age1...'                  # public recipient only
export BACKUP_DIR="$HOME/crownd-backups"
export BACKUP_KEEP_DAYS=30
./scripts/backup_postgres.sh
```

The backup role should have only the privileges needed to read the database and sequence state. Use provider-specific TLS/CA parameters through supported `PG*`/service configuration, verify server identity, and ensure the network is private. Do not put a password into `PGHOST`, `PGDATABASE`, `AGE_RECIPIENT`, or command-line arguments.

## Local isolated restore rehearsal

The helper refuses non-loopback hosts, requires an exact confirmation variable, only creates a *new* database named `crownd_restore_test_*`, and never passes `--clean`/`--create` to `pg_restore`. A failed restore may leave its new isolated test database for inspection; drop it manually only after confirming the target name and host.

```sh
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=crownd_recovery
export PGPASSFILE="$HOME/.pgpass-crownd-recovery"
export AGE_IDENTITY_FILE="$HOME/.config/age/identities.txt" # private; chmod 600, never commit
backup="$HOME/crownd-backups/crownd-YYYYMMDDTHHMMSSZ.dump.age"
target=crownd_restore_test_20261125
CONFIRM_RESTORE_TARGET="$target" ./scripts/restore_postgres_test.sh "$backup" "$target"
```

After restore, connect only to the generated test database and verify:

```sql
SELECT version_num FROM alembic_version;
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM orders;
SELECT COUNT(*) FROM rewards;
SELECT COUNT(*) FROM ledger_entries;
SELECT COUNT(*) FROM email_deliveries;
```

Then run the same release candidate's API readiness/integration checks against the test DB. Do not use this local-only helper to restore a production DB.

## Production recovery procedure

1. Declare an incident and pause writers/worker processing as appropriate. Record the target database and the selected backup timestamp/restore point.
2. Provision a *new* isolated PostgreSQL database using the provider's documented procedure; do not overwrite the existing production database during rehearsal.
3. Retrieve the private age identity through the approved secret manager and decrypt to a stream/file with restricted permissions. Verify the encrypted backup checksum/integrity and decryptability before cutting traffic.
4. Restore using the provider-supported PostgreSQL tools and required TLS settings. The repository helper intentionally refuses remote targets; adapt a separately reviewed, provider-specific runbook rather than bypassing its safeguards.
5. Verify database version, Alembic revision, foreign keys, counts/reconciliation, API readiness, and a read-only representative workflow. Check that the deployed application/schema versions are compatible.
6. Route traffic to the restored DB only with explicit incident-lead approval. Preserve the failed original DB read-only for forensic/recovery work where possible.
7. Re-enable writer traffic and worker once application checks pass. Confirm backups resume and document actual recovery duration/data loss.

Prefer roll-forward code fixes for a bad migration. Before a planned schema migration, take and validate a backup, run the one-shot migration job once, verify the Alembic version and readiness, and keep the previous compatible application image available. Restore to a new database and switch configuration only after a tested recovery decision; do not assume every historical Alembic downgrade is safe or reversible.
