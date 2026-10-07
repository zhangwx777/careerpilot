"""Immutable migration registry. Add a new numbered file for every schema change."""

from app.migrations.versions.v0001_bootstrap import upgrade as bootstrap_tables
from app.migrations.versions.v0002_legacy_schema import upgrade as adopt_legacy_schema
from app.migrations.versions.v0003_task_dispatch_metrics import upgrade as add_task_metrics

MIGRATIONS = (
    (1, "bootstrap_tables", bootstrap_tables),
    (2, "adopt_legacy_schema", adopt_legacy_schema),
    (3, "task_dispatch_metrics", add_task_metrics),
)
