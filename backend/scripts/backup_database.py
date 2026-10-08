"""Create and restore versioned PostgreSQL backups with matching config keys."""

from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from urllib.parse import parse_qsl, unquote, urlsplit


class BackupError(RuntimeError):
    pass


_FORMAT_VERSION = 2
_DATABASE_FILE = "database.dump"
_MANIFEST_FILE = "manifest.json"
_SECRET_FILE = ".llm_config_secret"
_SECRET_KEYRING_DIR = ".llm_config_legacy_keys"
_BACKUP_KEYRING_DIR = "config_secret_keys"
_PG_OPTIONS = {
    "application_name": "PGAPPNAME",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
}


def _config_secret_path() -> Path:
    data_dir = os.environ.get("CAREERPILOT_DATA_DIR")
    if data_dir:
        return Path(data_dir) / _SECRET_FILE
    return Path(__file__).resolve().parents[2] / _SECRET_FILE


def _legacy_config_secret_paths(primary_secret: Path) -> tuple[Path, ...]:
    app_root = os.environ.get("CAREERPILOT_APP_ROOT")
    if app_root:
        packaged_root = Path(app_root)
        candidates = [
            packaged_root.parent / _SECRET_FILE,
            packaged_root / _SECRET_FILE,
        ]
    else:
        candidates = [Path(__file__).resolve().parents[2] / _SECRET_FILE]

    primary = primary_secret.resolve()
    candidates.extend(
        sorted((primary_secret.parent / _SECRET_KEYRING_DIR).glob("*.key"))
    )
    if app_root:
        candidates.extend(
            sorted((Path(app_root) / _SECRET_KEYRING_DIR).glob("*.key"))
        )
    unique = {}
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved != primary:
            unique.setdefault(resolved, resolved)
    return tuple(unique.values())


def _read_fernet_key(path: Path) -> bytes | None:
    try:
        key = path.read_bytes().strip()
    except OSError:
        return None
    try:
        decoded = base64.b64decode(key, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None
    return key if len(decoded) == 32 else None


def _packaged_database_url(port: int) -> str:
    return f"postgresql+psycopg://qiuzhao_app@127.0.0.1:{port}/postgres"


@contextmanager
def _database_url_for_cli(command: str) -> Iterator[str]:
    data_dir = os.environ.get("CAREERPILOT_DATA_DIR")
    app_root = os.environ.get("CAREERPILOT_APP_ROOT")
    packaged_desktop = bool(data_dir and app_root)
    configured_url = None
    if not packaged_desktop:
        try:
            from pydantic import ValidationError
        except ImportError:
            configured_url = None
        else:
            try:
                from app.config import settings

                configured_url = settings.database_url
            except ImportError:
                configured_url = None
            except ValidationError as exc:
                raise BackupError(
                    "无法读取数据库配置；请设置 DATABASE_URL 或检查项目 .env"
                ) from exc
    if configured_url:
        yield configured_url
        return

    if not data_dir or not app_root:
        raise BackupError("需要 DATABASE_URL 或 CareerPilot 桌面数据目录")
    data_path = Path(data_dir)
    state_file = data_path / "runtime.json"
    if state_file.is_file():
        if command == "restore":
            raise BackupError("恢复前请先退出 CareerPilot，避免覆盖正在使用的数据库")
        try:
            port = int(json.loads(state_file.read_text(encoding="utf-8"))["db_port"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError("桌面运行状态文件无效，请重启 CareerPilot 后重试") from exc
        if not 1 <= port <= 65535:
            raise BackupError("桌面数据库端口无效")
        yield _packaged_database_url(port)
        return

    postgres_data = data_path / "postgres"
    if not (postgres_data / "PG_VERSION").is_file():
        raise BackupError("找不到桌面 PostgreSQL 数据目录")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log_dir = data_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    pg_ctl = _postgres_tool("pg_ctl")
    start = subprocess.run(
        [
            pg_ctl,
            "-D",
            str(postgres_data),
            "-l",
            str(log_dir / "backup-postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {port}",
            "start",
            "-w",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if start.returncode != 0:
        raise BackupError("桌面 PostgreSQL 无法启动；请确认应用已完全退出")
    try:
        yield _packaged_database_url(port)
    finally:
        stop = subprocess.run(
            [pg_ctl, "-D", str(postgres_data), "stop", "-m", "fast", "-w"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if stop.returncode != 0:
            raise BackupError("备份操作后桌面 PostgreSQL 未能正常停止")


def _connection_environment(database_url: str) -> tuple[dict[str, str], str]:
    try:
        parsed = urlsplit(
            database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        )
        port = parsed.port
    except ValueError as exc:
        raise BackupError("DATABASE_URL 格式无效") from exc
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.path.strip("/"):
        raise BackupError("DATABASE_URL 必须指向 PostgreSQL 数据库")

    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if port:
        env["PGPORT"] = str(port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        env_key = _PG_OPTIONS.get(key)
        if env_key:
            env[env_key] = value
    return env, env["PGDATABASE"]


def _postgres_tool(name: str) -> str:
    executable = f"{name}.exe" if os.name == "nt" else name
    configured_bin = os.environ.get("CAREERPILOT_PG_BIN")
    candidates = []
    if configured_bin:
        candidates.append(Path(configured_bin) / executable)
    app_root = os.environ.get("CAREERPILOT_APP_ROOT")
    if app_root:
        candidates.append(
            Path(app_root).parent / "runtime" / "postgresql" / "bin" / executable
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(executable)
    if found:
        return found
    raise BackupError(
        f"找不到 PostgreSQL 客户端 {executable}；请安装客户端或设置 CAREERPILOT_PG_BIN"
    )


def _restrict_permissions(path: Path, *, directory: bool = False) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    identity = subprocess.run(
        ["whoami"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if identity.returncode != 0 or not identity.stdout.strip():
        raise BackupError("无法确定当前 Windows 用户，备份权限未能安全设置")
    rights = "(OI)(CI)F" if directory else "F"
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity.stdout.strip()}:{rights}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError("无法限制备份目录的 Windows 文件权限")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError(f"PostgreSQL 客户端执行失败（退出码 {result.returncode}）")


def create_backup(
    output_dir: Path,
    database_url: str,
    secret_path: Path | None = None,
) -> Path:
    target = output_dir.expanduser().resolve()
    if target.exists():
        raise BackupError("备份目录已存在；请指定一个新的目录")
    env, _ = _connection_environment(database_url)
    secret = secret_path or _config_secret_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        _restrict_permissions(staging, directory=True)
        dump_path = staging / _DATABASE_FILE
        _run(
            [
                _postgres_tool("pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(dump_path),
            ],
            env,
        )
        _restrict_permissions(dump_path)
        primary_key = _read_fernet_key(secret)
        legacy_keys = []
        seen_keys = {primary_key} if primary_key is not None else set()
        for legacy_path in _legacy_config_secret_paths(secret):
            key = _read_fernet_key(legacy_path)
            if key is not None and key not in seen_keys:
                legacy_keys.append(key)
                seen_keys.add(key)

        secret_info = {
            "included": bool(primary_key or legacy_keys),
            "primary": None,
            "legacy": [],
        }
        if primary_key is not None:
            primary_path = staging / _SECRET_FILE
            primary_path.write_bytes(primary_key)
            _restrict_permissions(primary_path)
            secret_info["primary"] = {
                "file": _SECRET_FILE,
                "sha256": _sha256(primary_path),
            }
        if legacy_keys:
            keyring_dir = staging / _BACKUP_KEYRING_DIR
            keyring_dir.mkdir()
            _restrict_permissions(keyring_dir, directory=True)
            for key in legacy_keys:
                fingerprint = hashlib.sha256(key).hexdigest()
                relative_path = f"{_BACKUP_KEYRING_DIR}/legacy-{fingerprint}.key"
                key_path = staging / relative_path
                key_path.write_bytes(key)
                _restrict_permissions(key_path)
                secret_info["legacy"].append(
                    {"file": relative_path, "sha256": _sha256(key_path)}
                )
        manifest = {
            "format_version": _FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": {"file": _DATABASE_FILE, "sha256": _sha256(dump_path)},
            "config_secrets": secret_info,
        }
        manifest_path = staging / _MANIFEST_FILE
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _restrict_permissions(manifest_path)
        os.replace(staging, target)
        return target
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _read_backup(backup_dir: Path) -> tuple[dict, Path, Path | None, list[Path]]:
    root = backup_dir.expanduser().resolve()
    try:
        manifest = json.loads((root / _MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("备份清单缺失或格式无效") from exc
    if not isinstance(manifest, dict):
        raise BackupError("备份清单格式无效")
    if manifest.get("format_version") != _FORMAT_VERSION:
        raise BackupError("不支持此备份格式版本")
    database = manifest.get("database")
    if not isinstance(database, dict) or database.get("file") != _DATABASE_FILE:
        raise BackupError("备份清单中的数据库文件无效")
    dump_path = root / _DATABASE_FILE
    if not dump_path.is_file() or not hmac.compare_digest(
        _sha256(dump_path), str(database.get("sha256", ""))
    ):
        raise BackupError("数据库备份校验失败，文件可能不完整或已损坏")

    secret_info = manifest.get("config_secrets")
    if not isinstance(secret_info, dict) or not isinstance(
        secret_info.get("included"), bool
    ):
        raise BackupError("备份清单中的加密密钥信息无效")
    primary_info = secret_info.get("primary")
    primary_secret = None
    if primary_info is not None:
        if not isinstance(primary_info, dict) or primary_info.get("file") != _SECRET_FILE:
            raise BackupError("备份清单中的加密密钥文件无效")
        primary_secret = root / _SECRET_FILE
        if not primary_secret.is_file() or not hmac.compare_digest(
            _sha256(primary_secret), str(primary_info.get("sha256", ""))
        ) or _read_fernet_key(primary_secret) is None:
            raise BackupError("加密密钥校验失败，无法安全恢复")

    legacy_info = secret_info.get("legacy")
    if not isinstance(legacy_info, list):
        raise BackupError("备份清单中的旧密钥列表无效")
    legacy_secrets = []
    seen_legacy_files = set()
    for item in legacy_info:
        if not isinstance(item, dict):
            raise BackupError("备份清单中的旧密钥信息无效")
        relative_path = item.get("file")
        if (
            not isinstance(relative_path, str)
            or not re.fullmatch(
                rf"{_BACKUP_KEYRING_DIR}/legacy-[0-9a-f]{{64}}\.key",
                relative_path,
            )
            or relative_path in seen_legacy_files
        ):
            raise BackupError("备份清单中的旧密钥文件无效")
        seen_legacy_files.add(relative_path)
        legacy_path = root / relative_path
        if not legacy_path.is_file() or not hmac.compare_digest(
            _sha256(legacy_path), str(item.get("sha256", ""))
        ) or _read_fernet_key(legacy_path) is None:
            raise BackupError("旧加密密钥校验失败，无法安全恢复")
        legacy_secrets.append(legacy_path)

    has_secrets = primary_secret is not None or bool(legacy_secrets)
    if secret_info["included"] != has_secrets:
        raise BackupError("备份清单中的加密密钥状态无效")
    return manifest, dump_path, primary_secret, legacy_secrets


def restore_backup(
    backup_dir: Path,
    database_url: str,
    secret_path: Path | None = None,
    *,
    confirm: bool = False,
    replace_secret: bool = False,
) -> None:
    if not confirm:
        raise BackupError("恢复会替换目标数据库；请显式确认后重试")
    _, dump_path, backup_secret, backup_legacy_secrets = _read_backup(backup_dir)
    env, database_name = _connection_environment(database_url)
    target_secret = secret_path or _config_secret_path()
    staged_secret = None
    staged_keyring = None
    database_restored = False

    try:
        if backup_secret:
            current_key = _read_fernet_key(target_secret)
            backup_key = _read_fernet_key(backup_secret)
            if target_secret.is_file() and not hmac.compare_digest(
                current_key or b"", backup_key or b""
            ) and not replace_secret:
                raise BackupError(
                    "目标加密密钥与备份不一致；确认要替换时使用 --replace-secret"
                )
            if not target_secret.is_file() or replace_secret:
                target_secret.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    prefix=f".{target_secret.name}.restore-",
                    dir=target_secret.parent,
                    delete=False,
                ) as temporary:
                    staged_secret = Path(temporary.name)
                shutil.copyfile(backup_secret, staged_secret)
                _restrict_permissions(staged_secret)

        if backup_legacy_secrets:
            target_secret.parent.mkdir(parents=True, exist_ok=True)
            staged_keyring = Path(
                tempfile.mkdtemp(
                    prefix=f".{_SECRET_KEYRING_DIR}.restore-",
                    dir=target_secret.parent,
                )
            )
            _restrict_permissions(staged_keyring, directory=True)
            for backup_key in backup_legacy_secrets:
                staged_key = staged_keyring / backup_key.name
                shutil.copyfile(backup_key, staged_key)
                _restrict_permissions(staged_key)

        _run(
            [
                _postgres_tool("pg_restore"),
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                database_name,
                str(dump_path),
            ],
            env,
        )
        database_restored = True
        if staged_keyring:
            keyring_dir = target_secret.parent / _SECRET_KEYRING_DIR
            keyring_dir.mkdir(parents=True, exist_ok=True)
            _restrict_permissions(keyring_dir, directory=True)
            for staged_key in staged_keyring.iterdir():
                target_key = keyring_dir / staged_key.name
                if target_key.exists():
                    if not hmac.compare_digest(
                        _read_fernet_key(target_key) or b"",
                        _read_fernet_key(staged_key) or b"",
                    ):
                        raise BackupError(
                            "数据库已恢复，但旧密钥文件名冲突；请保留备份目录并检查密钥环"
                        )
                    staged_key.unlink()
                else:
                    os.replace(staged_key, target_key)
        if staged_secret:
            try:
                os.replace(staged_secret, target_secret)
            except OSError as exc:
                raise BackupError(
                    "数据库已恢复，但加密密钥无法安装；保留备份目录并重试密钥恢复"
                ) from exc
            staged_secret = None
    except OSError as exc:
        message = (
            "数据库已恢复，但密钥文件无法安装；保留备份目录并检查数据目录权限"
            if database_restored
            else "无法准备恢复密钥；请检查数据目录权限"
        )
        raise BackupError(message) from exc
    finally:
        if staged_secret and staged_secret.exists():
            staged_secret.unlink()
        if staged_keyring and staged_keyring.exists():
            shutil.rmtree(staged_keyring, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", help="导出数据库和本机加密密钥")
    backup_parser.add_argument("--output", required=True, type=Path, help="新的备份目录")
    restore_parser = commands.add_parser("restore", help="恢复数据库和匹配的加密密钥")
    restore_parser.add_argument("backup_dir", type=Path)
    restore_parser.add_argument(
        "--confirm", action="store_true", help="确认替换目标数据库内容"
    )
    restore_parser.add_argument(
        "--replace-secret", action="store_true", help="用备份中的密钥替换现有密钥"
    )
    args = parser.parse_args()
    try:
        with _database_url_for_cli(args.command) as database_url:
            if args.command == "backup":
                output = create_backup(args.output, database_url)
                print(f"备份完成：{output}")
            else:
                restore_backup(
                    args.backup_dir,
                    database_url,
                    confirm=args.confirm,
                    replace_secret=args.replace_secret,
                )
                print("数据库恢复完成")
    except (BackupError, OSError) as exc:
        print(f"备份操作失败：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
