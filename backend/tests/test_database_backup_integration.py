"""Real pg_dump/pg_restore coverage for disposable integration databases."""

from cryptography.fernet import Fernet
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from scripts.backup_database import create_backup, restore_backup


@unittest.skipUnless(
    os.environ.get("CAREERPILOT_RUN_BACKUP_INTEGRATION") == "1",
    "requires disposable PostgreSQL databases and pg_dump/pg_restore",
)
class DatabaseBackupIntegrationTests(unittest.TestCase):
    def setUp(self):
        database_url = os.environ.get("TEST_DATABASE_URL")
        if not database_url:
            self.fail("TEST_DATABASE_URL is required for backup integration tests")

        self.base_url = make_url(database_url)
        self.admin_engine = create_engine(self.base_url.set(database="postgres"))
        self.engines = []
        self.database_names = []
        self.temporary = TemporaryDirectory(prefix="careerpilot-backup-integration-")
        self.root = Path(self.temporary.name)
        self.addCleanup(self._cleanup)

        self.source_name, self.source_url, self.source_engine = self._create_database("source")
        self.target_name, self.target_url, self.target_engine = self._create_database("target")

    def _create_database(self, label: str):
        name = f"cp_backup_{label}_{uuid.uuid4().hex[:10]}"
        with self.admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        self.database_names.append(name)
        url = self.base_url.set(database=name)
        engine = create_engine(url)
        self.engines.append(engine)
        return name, url, engine

    def _cleanup(self):
        for engine in self.engines:
            engine.dispose()
        for name in reversed(self.database_names):
            with self.admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
        self.admin_engine.dispose()
        self.temporary.cleanup()

    def test_real_dump_restore_preserves_rows_and_historical_encryption_keys(self):
        source_data = self.root / "source-data"
        source_data.mkdir()
        current_key = Fernet.generate_key()
        legacy_key = Fernet.generate_key()
        secret_path = source_data / ".llm_config_secret"
        secret_path.write_bytes(current_key)
        keyring = source_data / ".llm_config_legacy_keys"
        keyring.mkdir()
        legacy_path = keyring / f"legacy-{hashlib.sha256(legacy_key).hexdigest()}.key"
        legacy_path.write_bytes(legacy_key)
        encrypted_value = Fernet(legacy_key).encrypt(b"historical snapshot").decode("ascii")

        with self.source_engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE backup_probe (id integer PRIMARY KEY, encrypted_value text NOT NULL)"
            )
            connection.execute(
                text("INSERT INTO backup_probe (id, encrypted_value) VALUES (1, :value)"),
                {"value": encrypted_value},
            )

        backup_dir = create_backup(
            self.root / "backup",
            self.source_url.render_as_string(hide_password=False),
            secret_path,
        )
        target_data = self.root / "target-data"
        target_secret = target_data / ".llm_config_secret"
        restore_backup(
            backup_dir,
            self.target_url.render_as_string(hide_password=False),
            target_secret,
            confirm=True,
        )

        with self.target_engine.connect() as connection:
            restored = connection.execute(
                text("SELECT id, encrypted_value FROM backup_probe")
            ).one()
        self.assertEqual(restored.id, 1)
        self.assertEqual(restored.encrypted_value, encrypted_value)
        self.assertTrue(target_secret.is_file())
        self.assertTrue(list((target_data / ".llm_config_legacy_keys").glob("*.key")))

        environment = os.environ.copy()
        environment["CAREERPILOT_DATA_DIR"] = str(target_data)
        environment.pop("CAREERPILOT_APP_ROOT", None)
        backend_root = Path(__file__).resolve().parents[1]
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(backend_root), existing_pythonpath) if item
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from app.llm.config_store import decrypt_text; "
                "print(decrypt_text(sys.argv[1]))",
                encrypted_value,
            ],
            cwd=backend_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "historical snapshot")


if __name__ == "__main__":
    unittest.main()
