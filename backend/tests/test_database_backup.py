import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from scripts.backup_database import (
    BackupError,
    _database_url_for_cli,
    create_backup,
    restore_backup,
)


DATABASE_URL = "postgresql+psycopg://tester:p%40ss@db.example:5440/careerpilot?sslmode=require"


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.secret = self.root / ".llm_config_secret"
        self.secret.write_bytes(Fernet.generate_key())

    def tearDown(self):
        self.temp.cleanup()

    def _successful_tool(self, command, **_kwargs):
        if "--file" in command:
            Path(command[command.index("--file") + 1]).write_bytes(b"custom pg dump")
        return subprocess.CompletedProcess(command, 0)

    def _backup(self, path: Path):
        with patch("scripts.backup_database._postgres_tool", return_value="pg_dump"), patch(
            "scripts.backup_database.subprocess.run", side_effect=self._successful_tool
        ) as run:
            result = create_backup(path, DATABASE_URL, self.secret)
        return result, run

    def test_backup_records_checksums_and_passes_credentials_outside_argv(self):
        backup_dir, run = self._backup(self.root / "backup")
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertTrue(manifest["config_secrets"]["included"])
        self.assertEqual((backup_dir / ".llm_config_secret").read_bytes(), self.secret.read_bytes())
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("p@ss", " ".join(command))
        self.assertEqual(environment["PGPASSWORD"], "p@ss")
        self.assertEqual(environment["PGHOST"], "db.example")
        self.assertEqual(environment["PGPORT"], "5440")
        self.assertEqual(environment["PGDATABASE"], "careerpilot")
        self.assertEqual(environment["PGSSLMODE"], "require")
        if os.name != "nt":
            self.assertEqual((backup_dir.stat().st_mode & 0o777), 0o700)
            self.assertEqual(((backup_dir / ".llm_config_secret").stat().st_mode & 0o777), 0o600)

    def test_invalid_database_url_is_reported_as_backup_error(self):
        with self.assertRaisesRegex(BackupError, "DATABASE_URL 格式无效"):
            from scripts.backup_database import _connection_environment

            _connection_environment("postgresql://user:password@db.example:invalid/db")

    def test_missing_source_configuration_has_actionable_error(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "", "CAREERPILOT_APP_ROOT": "", "CAREERPILOT_DATA_DIR": ""},
            clear=True,
        ), patch(
            "app.config.settings", SimpleNamespace(database_url="")
        ), self.assertRaisesRegex(BackupError, "DATABASE_URL"):
            with _database_url_for_cli("backup"):
                self.fail("missing source configuration must fail before database access")

    def test_source_cli_uses_the_same_database_setting_as_the_application(self):
        application_url = "postgresql+psycopg://app:secret@dotenv.example/careerpilot"
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql+psycopg://env:secret@other/db"},
        ), patch(
            "app.config.settings", SimpleNamespace(database_url=application_url)
        ):
            with _database_url_for_cli("backup") as url:
                self.assertEqual(url, application_url)

    def test_backup_failure_removes_staging_directory(self):
        def fail_after_partial_dump(command, **_kwargs):
            Path(command[command.index("--file") + 1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1)

        target = self.root / "backup"
        with patch("scripts.backup_database._postgres_tool", return_value="pg_dump"), patch(
            "scripts.backup_database.subprocess.run", side_effect=fail_after_partial_dump
        ), self.assertRaisesRegex(BackupError, "客户端执行失败"):
            create_backup(target, DATABASE_URL, self.secret)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".backup.tmp-*")), [])

    def test_backup_permission_failure_removes_staging_directory(self):
        target = self.root / "backup"
        with patch(
            "scripts.backup_database._restrict_permissions",
            side_effect=BackupError("permission setup failed"),
        ), self.assertRaisesRegex(BackupError, "permission setup failed"):
            create_backup(target, DATABASE_URL, self.secret)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".backup.tmp-*")), [])

    def test_restore_requires_confirmation_and_valid_checksums(self):
        backup_dir, _ = self._backup(self.root / "backup")
        with self.assertRaisesRegex(BackupError, "显式确认"):
            restore_backup(backup_dir, DATABASE_URL, self.secret)

        (backup_dir / "database.dump").write_bytes(b"corrupt")
        with patch("scripts.backup_database.subprocess.run") as run, self.assertRaisesRegex(
            BackupError, "校验失败"
        ):
            restore_backup(backup_dir, DATABASE_URL, self.secret, confirm=True)
        run.assert_not_called()

    def test_restore_refuses_key_mismatch_until_explicitly_replaced(self):
        backup_dir, _ = self._backup(self.root / "backup")
        target_secret = self.root / "target" / ".llm_config_secret"
        target_secret.parent.mkdir()
        target_secret.write_bytes(b"different-key")

        with patch("scripts.backup_database._postgres_tool", return_value="pg_restore"), patch(
            "scripts.backup_database.subprocess.run", side_effect=self._successful_tool
        ) as run, self.assertRaisesRegex(BackupError, "--replace-secret"):
            restore_backup(backup_dir, DATABASE_URL, target_secret, confirm=True)
        run.assert_not_called()

        with patch("scripts.backup_database._postgres_tool", return_value="pg_restore"), patch(
            "scripts.backup_database.subprocess.run", side_effect=self._successful_tool
        ) as run:
            restore_backup(
                backup_dir,
                DATABASE_URL,
                target_secret,
                confirm=True,
                replace_secret=True,
            )
        self.assertEqual(target_secret.read_bytes(), self.secret.read_bytes())
        command = run.call_args.args[0]
        self.assertIn("--single-transaction", command)
        self.assertNotIn("p@ss", " ".join(command))

    def test_failed_restore_keeps_existing_secret(self):
        backup_dir, _ = self._backup(self.root / "backup")
        target_secret = self.root / "target" / ".llm_config_secret"
        target_secret.parent.mkdir()
        target_secret.write_bytes(b"old-key")
        fail = lambda command, **_kwargs: subprocess.CompletedProcess(command, 2)

        with patch("scripts.backup_database._postgres_tool", return_value="pg_restore"), patch(
            "scripts.backup_database.subprocess.run", side_effect=fail
        ), self.assertRaisesRegex(BackupError, "客户端执行失败"):
            restore_backup(
                backup_dir,
                DATABASE_URL,
                target_secret,
                confirm=True,
                replace_secret=True,
            )
        self.assertEqual(target_secret.read_bytes(), b"old-key")

    def _backup_with_legacy_key(self, backup_path: Path, *, include_primary=True):
        data_dir = self.root / "old-data"
        data_dir.mkdir(exist_ok=True)
        primary_secret = data_dir / ".llm_config_secret"
        if include_primary:
            primary_secret.write_bytes(Fernet.generate_key())
        install_root = self.root / "old-install"
        app_root = install_root / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        legacy_key = install_root / ".llm_config_secret"
        legacy_key.write_bytes(Fernet.generate_key())
        keyring_dir = data_dir / ".llm_config_legacy_keys"
        keyring_dir.mkdir()
        keyring_key = keyring_dir / "previous-install.key"
        keyring_key.write_bytes(Fernet.generate_key())
        environment = {
            "CAREERPILOT_DATA_DIR": str(data_dir),
            "CAREERPILOT_APP_ROOT": str(app_root),
        }
        with patch.dict(os.environ, environment), patch(
            "scripts.backup_database._postgres_tool", return_value="pg_dump"
        ), patch(
            "scripts.backup_database.subprocess.run", side_effect=self._successful_tool
        ):
            backup = create_backup(backup_path, DATABASE_URL, primary_secret)
        return backup, primary_secret, legacy_key, keyring_key

    def test_backup_includes_legacy_key_when_primary_is_missing(self):
        backup_dir, _, _, _ = self._backup_with_legacy_key(
            self.root / "legacy-only-backup", include_primary=False
        )
        manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
        secret_info = manifest["config_secrets"]
        self.assertTrue(secret_info["included"])
        self.assertIsNone(secret_info["primary"])
        self.assertEqual(len(secret_info["legacy"]), 2)

    def test_restore_preserves_primary_and_legacy_fernet_keys(self):
        backup_dir, primary_secret, legacy_secret, keyring_secret = self._backup_with_legacy_key(
            self.root / "multi-key-backup"
        )
        primary_ciphertext = Fernet(primary_secret.read_bytes()).encrypt(
            b"current provider setting"
        )
        legacy_ciphertext = Fernet(legacy_secret.read_bytes()).encrypt(
            b"historical task snapshot"
        )
        keyring_ciphertext = Fernet(keyring_secret.read_bytes()).encrypt(
            b"older task snapshot"
        )
        target_data_dir = self.root / "restored-data"
        target_secret = target_data_dir / ".llm_config_secret"
        target_app_root = self.root / "new-install" / "app"
        with patch("scripts.backup_database._postgres_tool", return_value="pg_restore"), patch(
            "scripts.backup_database.subprocess.run", side_effect=self._successful_tool
        ):
            restore_backup(backup_dir, DATABASE_URL, target_secret, confirm=True)

        self.assertEqual(target_secret.read_bytes(), primary_secret.read_bytes())
        restored_keys = list((target_data_dir / ".llm_config_legacy_keys").glob("*.key"))
        self.assertEqual(len(restored_keys), 2)
        probe = (
            "from app.llm.config_store import decrypt_text; "
            f"assert decrypt_text({primary_ciphertext.decode('ascii')!r}) "
            "== 'current provider setting'; "
            f"assert decrypt_text({legacy_ciphertext.decode('ascii')!r}) "
            "== 'historical task snapshot'; "
            f"assert decrypt_text({keyring_ciphertext.decode('ascii')!r}) "
            "== 'older task snapshot'"
        )
        environment = os.environ.copy()
        environment.update(
            {
                "CAREERPILOT_DATA_DIR": str(target_data_dir),
                "CAREERPILOT_APP_ROOT": str(target_app_root),
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_restore_permission_failure_cleans_staged_keys(self):
        backup_dir, _, _, _ = self._backup_with_legacy_key(
            self.root / "permission-backup"
        )
        target_secret = self.root / "permission-target" / ".llm_config_secret"
        calls = 0

        def fail_legacy_staging(_path, *, directory=False):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BackupError("permission setup failed")

        with patch(
            "scripts.backup_database._restrict_permissions",
            side_effect=fail_legacy_staging,
        ), patch("scripts.backup_database._postgres_tool", return_value="pg_restore"), patch(
            "scripts.backup_database.subprocess.run"
        ) as run, self.assertRaisesRegex(BackupError, "permission setup failed"):
            restore_backup(backup_dir, DATABASE_URL, target_secret, confirm=True)

        run.assert_not_called()
        self.assertEqual(list(target_secret.parent.glob(".*.restore-*")), [])

    def test_packaged_backup_starts_and_stops_embedded_postgres(self):
        data_dir = self.root / "CareerPilot"
        postgres_data = data_dir / "postgres"
        postgres_data.mkdir(parents=True)
        (postgres_data / "PG_VERSION").write_text("18", encoding="ascii")
        environment = {
            "DATABASE_URL": "postgresql+psycopg://other:secret@remote.example/production",
            "CAREERPILOT_DATA_DIR": str(data_dir),
            "CAREERPILOT_APP_ROOT": str(self.root / "install" / "app"),
        }
        with patch.dict(os.environ, environment), patch(
            "scripts.backup_database._postgres_tool", return_value="pg_ctl"
        ), patch(
            "scripts.backup_database.subprocess.run",
            return_value=subprocess.CompletedProcess(["pg_ctl"], 0),
        ) as run:
            with _database_url_for_cli("backup") as url:
                self.assertRegex(url, r"qiuzhao_app@127\.0\.0\.1:\d+/postgres")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][-2:], ["start", "-w"])
        self.assertEqual(run.call_args_list[1].args[0][-4:], ["stop", "-m", "fast", "-w"])

    def test_packaged_restore_requires_desktop_to_be_closed(self):
        data_dir = self.root / "CareerPilot"
        data_dir.mkdir()
        (data_dir / "runtime.json").write_text('{"db_port": 55432}', encoding="utf-8")
        environment = {
            "DATABASE_URL": "postgresql+psycopg://other:secret@remote.example/production",
            "CAREERPILOT_DATA_DIR": str(data_dir),
            "CAREERPILOT_APP_ROOT": str(self.root / "install" / "app"),
        }
        with patch.dict(os.environ, environment), patch(
            "scripts.backup_database.subprocess.run"
        ) as run, self.assertRaisesRegex(BackupError, "退出 CareerPilot"):
            with _database_url_for_cli("restore"):
                self.fail("restore must not connect to a running desktop database")
        run.assert_not_called()

    def test_frozen_backend_routes_backup_command_to_utility(self):
        import sys

        launcher_path = (
            Path(__file__).resolve().parents[2]
            / "packaging"
            / "runtime"
            / "launcher_entry.py"
        )
        spec = importlib.util.spec_from_file_location("careerpilot_launcher", launcher_path)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        app_root = self.root / "install" / "app"
        backend_root = app_root / "backend"
        backend_root.mkdir(parents=True)
        (backend_root / "packaged_server.py").write_text("", encoding="utf-8")
        local_app_data = self.root / "local-app-data"
        argv = ["CareerPilotBackend.exe", "backup", "--output", "snapshot"]

        with patch.dict(
            os.environ,
            {
                "CAREERPILOT_APP_ROOT": str(app_root),
                "LOCALAPPDATA": str(local_app_data),
            },
            clear=True,
        ), patch.object(launcher.sys, "argv", argv), patch.object(
            launcher.sys, "path", list(sys.path)
        ), patch.object(launcher.runpy, "run_module") as run_module:
            launcher.main()
            self.assertEqual(
                os.environ["CAREERPILOT_DATA_DIR"],
                str(local_app_data / "CareerPilot"),
            )
        run_module.assert_called_once_with("scripts.backup_database", run_name="__main__")


if __name__ == "__main__":
    unittest.main()
