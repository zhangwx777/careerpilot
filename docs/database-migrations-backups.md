# Database migrations and backups

## Schema upgrades

The server applies pending PostgreSQL schema migrations before starting. The `careerpilot_schema_migrations` table records each applied version. A PostgreSQL advisory lock serializes simultaneous application starts, and the schema changes plus their ledger entries commit in one transaction.

Versions 1 and 2 establish the current tables and adopt the compatibility changes formerly run on every startup. Version 3 adds durable task execution metrics. Once applied, those legacy `ALTER` and normalization statements do not run again. Future schema changes must add a new numbered migration and registry entry; do not edit a migration that has shipped. An unknown or gapped migration history fails closed.

## Create a backup

For a source or Docker deployment, run the command from `backend` with `DATABASE_URL` configured and PostgreSQL 18 client tools (`pg_dump` and `pg_restore`) on `PATH`. The backend Docker image includes these clients:

```powershell
python -m scripts.backup_database backup --output "$env:LOCALAPPDATA\CareerPilot\backups\careerpilot-20261008"
```

The destination must be a new directory. It contains a custom-format `database.dump`, a checksum manifest, the current `.llm_config_secret` when present, and every valid legacy Fernet key still recognized by the app. Legacy keys are stored under `config_secret_keys/` so existing encrypted task snapshots remain readable after a restore. On the packaged Windows desktop, the same commands are available through the bundled backend executable:

```powershell
$backend = "$env:LOCALAPPDATA\Programs\CareerPilot\runtime\backend\CareerPilotBackend.exe"
& $backend backup --output "$env:LOCALAPPDATA\CareerPilot\backups\careerpilot-20261008"
```

The desktop command finds the bundled PostgreSQL 18 tools and the user data directory. It can back up while CareerPilot is open. The backup directory receives restrictive current-user Windows permissions (or mode `0700` on the directory and `0600` on files on Unix). The encryption keys are included as files, so keep the backup on a private, preferably disk-encrypted location.

## Restore a backup

Stop the application and worker before restoring. Source deployments need their configured `DATABASE_URL`; the packaged desktop command starts its bundled PostgreSQL temporarily when the app is closed.

```powershell
python -m scripts.backup_database restore "C:\path\to\careerpilot-20261008" --confirm
```

For the packaged desktop:

```powershell
& $backend restore "$env:LOCALAPPDATA\CareerPilot\backups\careerpilot-20261008" --confirm
```

Restore recreates the backed-up objects in the target database in one PostgreSQL transaction. The command verifies all checksums before changing the database. It installs the matching current and legacy keys only after the database restore succeeds. If the target already has a different current key, restore stops unless `--replace-secret` is explicitly supplied. Keep the backup directory until the restored app has opened and its saved model settings and history are readable.

## Verification

The migration integration tests check initialization idempotence, legacy-schema adoption, preserved rows, and fail-closed handling of unknown versions. Backup unit tests verify checksums, credential handling, restrictive permissions, failure cleanup, current and legacy Fernet key recovery, and packaged command routing. The Docker CI suite also runs a real `pg_dump`/`pg_restore` round-trip against two uniquely named disposable databases, then starts a fresh process to decrypt a value written with a historical Fernet key. It drops both databases during cleanup; never point restore tests at a user's active database.
