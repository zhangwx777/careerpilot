"""Transactional, ordered PostgreSQL schema migrations."""

from sqlalchemy import Connection, text

from app.migrations.versions import MIGRATIONS

_MIGRATION_TABLE = "careerpilot_schema_migrations"
_LOCK_ID = 684022310178


def apply_schema_migrations(connection: Connection) -> None:
    """Apply each pending schema migration once, in version order."""

    connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _LOCK_ID})
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} ("
            "version INTEGER PRIMARY KEY, "
            "name VARCHAR(120) NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    applied = [
        row.version
        for row in connection.execute(
            text(f"SELECT version FROM {_MIGRATION_TABLE} ORDER BY version")
        )
    ]
    known_versions = [version for version, _, _ in MIGRATIONS]
    if applied != known_versions[: len(applied)]:
        raise RuntimeError(
            "数据库迁移版本账本与当前程序不兼容，请先备份并检查数据库"
        )

    for version, name, upgrade in MIGRATIONS[len(applied) :]:
        upgrade(connection)
        connection.execute(
            text(
                f"INSERT INTO {_MIGRATION_TABLE} (version, name) "
                "VALUES (:version, :name)"
            ),
            {"version": version, "name": name},
        )
