"""Provider configuration and encrypted task snapshots.

Provider connection settings come from the local database and are captured in
encrypted task snapshots. Secrets are never returned to API callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.llm.prompts import PROMPT_VERSION
from app.llm.registry import PROVIDER_NAMES
from app.models import LLM_PROVIDER_NAMES, LlmProviderConfig, LlmSettings


PROVIDER_META = {
    "openai": {"label": "OpenAI", "description": "通用对话与结构化分析"},
    "anthropic": {"label": "Anthropic", "description": "长文本推理与面试分析"},
    "deepseek": {"label": "DeepSeek", "description": "中文技术分析与备战"},
    "qwen": {"label": "Qwen", "description": "中文通知与图片识别"},
}


class LlmConfigError(ValueError):
    """A safe, user-facing configuration error."""


class LlmModelsError(RuntimeError):
    """A safe, user-facing model catalogue error."""


CONFIG_SECRET_FILE = (
    Path(os.environ["CAREERPILOT_DATA_DIR"]) / ".llm_config_secret"
    if os.environ.get("CAREERPILOT_DATA_DIR")
    else Path(__file__).resolve().parents[3] / ".llm_config_secret"
)
CONFIG_SECRET_KEYRING_DIR = CONFIG_SECRET_FILE.parent / ".llm_config_legacy_keys"
_packaged_app_root = os.environ.get("CAREERPILOT_APP_ROOT")
LEGACY_CONFIG_SECRET_KEYRING_DIRS = (
    CONFIG_SECRET_KEYRING_DIR,
    *(
        (Path(_packaged_app_root) / ".llm_config_legacy_keys",)
        if _packaged_app_root
        else ()
    ),
    Path(__file__).resolve().parents[3] / ".llm_config_legacy_keys",
)
LEGACY_CONFIG_SECRET_FILES = tuple(
    candidate
    for candidate in (
        Path(_packaged_app_root).parent / ".llm_config_secret"
        if _packaged_app_root
        else None,
        Path(__file__).resolve().parents[3] / ".llm_config_secret",
    )
    if candidate is not None and candidate != CONFIG_SECRET_FILE
) + tuple(
    sorted(
        {
            path
            for directory in LEGACY_CONFIG_SECRET_KEYRING_DIRS
            for path in directory.glob("*.key")
        }
    )
)


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    api_key: str
    model: str
    api_base: str | None
    prompt_version: str = PROMPT_VERSION

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def validate_provider(provider: str) -> str:
    if provider not in LLM_PROVIDER_NAMES:
        raise LlmConfigError(f"不支持的模型厂商：{provider}")
    return provider


def validate_base_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LlmConfigError("Base URL 必须是完整的 http/https 地址")
    if parsed.username or parsed.password:
        raise LlmConfigError("Base URL 不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise LlmConfigError("Base URL 不应包含 query 或 fragment")
    return candidate.rstrip("/")


def _read_fernet(path: Path) -> Fernet | None:
    try:
        secret = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    try:
        return Fernet(secret.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def _fernet() -> Fernet:
    current = _read_fernet(CONFIG_SECRET_FILE)
    if current is not None:
        return current
    for legacy_path in LEGACY_CONFIG_SECRET_FILES:
        legacy = _read_fernet(legacy_path)
        if legacy is None:
            continue
        CONFIG_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_SECRET_FILE.write_text(
            legacy_path.read_text(encoding="ascii").strip(),
            encoding="ascii",
        )
        return legacy
    secret = Fernet.generate_key().decode("ascii")
    CONFIG_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_SECRET_FILE.write_text(secret, encoding="ascii")
    return Fernet(secret.encode("ascii"))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    encrypted = value.encode("ascii")
    candidates = [_fernet()]
    candidates.extend(
        legacy
        for path in LEGACY_CONFIG_SECRET_FILES
        if (legacy := _read_fernet(path)) is not None
    )
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return candidate.decrypt(encrypted).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            last_error = exc
    raise LlmConfigError(
        "本机模型配置密钥无法解密，请重新填写 API Key"
    ) from last_error


def get_effective_config(db: Session | None, provider: str) -> dict:
    """Return the web-configured LiteLLM settings."""

    validate_provider(provider)
    if db is None:
        raise LlmConfigError("请先在设置页完成模型配置")
    row = db.get(LlmProviderConfig, provider)
    if row is None or not row.enabled:
        raise LlmConfigError(f"模型 {provider} 尚未配置 API key 和 model")
    api_key = decrypt_text(row.encrypted_api_key) if row.encrypted_api_key else ""
    base_url = validate_base_url(row.base_url)
    return {
        "api_key": api_key,
        "api_base": base_url,
        "model": row.model,
    }


_MODEL_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
}


def _model_endpoint_candidates(provider: str, base_url: str | None) -> list[str]:
    """Build model-catalogue URLs for official and OpenAI-compatible endpoints.

    The settings page asks for an API root, but users commonly paste either a
    root without ``/v1`` or a chat-completions URL.  Try the normalized root
    first, then the conventional ``/v1/models`` path when it is not already
    present.  A 404 on the first candidate is therefore not mistaken for a
    network failure.
    """

    if not base_url:
        return [_MODEL_ENDPOINTS[provider]]
    endpoint = str(base_url).rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    if endpoint.endswith("/models"):
        return [endpoint]
    candidates = [f"{endpoint}/models"]
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        candidates.append(f"{endpoint}/v1/models")
    return list(dict.fromkeys(candidates))


def list_available_models(db: Session | None, provider: str, *, overrides: dict | None = None) -> list[str]:
    """Read a provider's model catalogue without persisting temporary fields."""

    validate_provider(provider)
    try:
        config = get_effective_config(db, provider)
    except LlmConfigError:
        if not overrides or not overrides.get("api_key"):
            raise
        config = {}
    config = {**config, **(overrides or {})}
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise LlmModelsError("请先填写 API key")
    base_url = config.get("api_base")
    endpoints = _model_endpoint_candidates(provider, base_url)
    # Some OpenAI-compatible gateways reject urllib's default
    # ``Python-urllib/...`` user agent even when the credentials are valid.
    headers = {"Accept": "application/json", "User-Agent": "qiuzhao-agent/0.1"}
    if provider == "anthropic":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = None
    last_http_error: HTTPError | None = None
    for endpoint in endpoints:
        request = Request(endpoint, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=settings.llm_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            last_http_error = exc
            if exc.code == 404 and endpoint != endpoints[-1]:
                continue
            if exc.code == 401:
                raise LlmModelsError("模型目录认证失败，请检查 API key") from None
            if exc.code == 403:
                raise LlmModelsError("模型目录访问被拒绝，可能是中转站的访问策略拦截") from None
            if exc.code == 404:
                raise LlmModelsError("模型目录不存在，请将 Base URL 填到供应商的 API 根路径（通常以 /v1 结尾）") from None
            raise LlmModelsError(f"模型目录返回 HTTP {exc.code}，请检查 Base URL") from None
        except (URLError, TimeoutError, json.JSONDecodeError, OSError):
            raise LlmModelsError("模型目录暂时不可用，请检查 Base URL 或网络") from None
    if payload is None:
        if last_http_error is not None:
            raise LlmModelsError("模型目录不存在，请将 Base URL 填到供应商的 API 根路径（通常以 /v1 结尾）") from None
        raise LlmModelsError("模型目录暂时不可用，请检查 Base URL 或网络") from None
    raw_models = None
    if isinstance(payload, dict):
        raw_models = payload.get("data") or payload.get("models") or payload.get("result")
        if isinstance(raw_models, dict):
            raw_models = raw_models.get("data") or raw_models.get("models")
    if not isinstance(raw_models, list):
        raise LlmModelsError("模型目录返回格式异常")
    models: list[str] = []
    for item in raw_models:
        candidate = item.get("id") if isinstance(item, dict) else item
        if isinstance(candidate, str) and candidate.strip() and candidate.strip() not in models:
            models.append(candidate.strip())
    if not models:
        raise LlmModelsError("该地址没有返回可用模型")
    return sorted(models, key=str.casefold)


def snapshot_for(db: Session, provider: str) -> str | None:
    """Encrypt the effective config for a resumable background task.

    In legacy env-only mode there is intentionally no database secret to use;
    returning None keeps the old deployment working and makes the task fall
    back to the current env config.
    """

    config = get_effective_config(db, provider)
    if not config.get("api_key") or not config.get("model"):
        raise LlmConfigError(f"模型 {provider} 尚未配置 API key 和 model")
    try:
        return encrypt_text(
            json.dumps(
                ProviderSnapshot(
                    provider=provider,
                    api_key=config["api_key"],
                    model=config["model"],
                    api_base=config.get("api_base"),
                ).as_dict(),
                ensure_ascii=False,
            )
        )
    except LlmConfigError:
        return None


def config_from_snapshot(token: str | None, db: Session | None, provider: str) -> dict:
    if not token:
        return get_effective_config(db, provider)
    try:
        payload = json.loads(decrypt_text(token))
        snapshot = ProviderSnapshot(**payload)
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise LlmConfigError("模型任务配置快照无效") from exc
    validate_provider(snapshot.provider)
    if snapshot.provider != provider:
        raise LlmConfigError("模型任务配置与 provider 不一致")
    return {
        "api_key": snapshot.api_key,
        "api_base": snapshot.api_base,
        "model": snapshot.model,
    }


def resolve_provider(db: Session | None, requested: str | None = None) -> str:
    if requested:
        provider = validate_provider(requested)
        config = get_effective_config(db, provider)
        if config.get("api_key") and config.get("model"):
            return provider
        raise LlmConfigError(f"模型 {provider} 尚未配置 API key 和 model")

    settings_row = db.get(LlmSettings, 1) if db is not None else None
    default = settings_row.default_provider if settings_row else None
    candidates = [default] if default else []
    if db is not None:
        database_rows = (
            db.query(LlmProviderConfig)
            .filter(LlmProviderConfig.enabled.is_(True))
            .order_by(LlmProviderConfig.updated_at.desc())
            .all()
        )
        candidates.extend(row.provider for row in database_rows)
    candidates.extend(name for name in PROVIDER_NAMES if name not in candidates)
    for provider in candidates:
        if provider:
            try:
                config = get_effective_config(db, provider)
            except LlmConfigError:
                continue
            if config.get("api_key") and config.get("model"):
                return provider
    raise LlmConfigError("暂无可用分析模型，请先在设置页完成配置")


ROLE_FIELDS = {
    "interview": "interview_provider",
    "planner": "planner_provider",
    "briefing": "briefing_provider",
    "vision": "vision_provider",
}

DEFAULT_SEARCH_TOOL = "search"


def resolve_role_provider(db: Session | None, role: str, requested: str | None = None) -> str:
    if role not in ROLE_FIELDS:
        raise LlmConfigError("未知模型业务角色")
    if requested:
        return resolve_provider(db, requested)
    settings_row = db.get(LlmSettings, 1) if db is not None else None
    configured = getattr(settings_row, ROLE_FIELDS[role], None) if settings_row else None
    return resolve_provider(db, configured) if configured else resolve_provider(db)


def save_role_providers(db: Session, roles: dict[str, str | None]) -> dict[str, str | None]:
    row = db.get(LlmSettings, 1)
    if row is None:
        row = LlmSettings(id=1)
        db.add(row)
    saved: dict[str, str | None] = {}
    for role, field in ROLE_FIELDS.items():
        provider = roles.get(role)
        if provider:
            provider = validate_provider(provider)
            get_effective_config(db, provider)
        setattr(row, field, provider)
        saved[role] = provider
    db.commit()
    return saved


def get_role_status(db: Session) -> dict[str, dict]:
    row = db.get(LlmSettings, 1)
    result = {}
    for role, field in ROLE_FIELDS.items():
        assigned = getattr(row, field, None) if row else None
        try:
            effective = resolve_role_provider(db, role)
            config = get_effective_config(db, effective)
            result[role] = {
                "provider": assigned,
                "effective_provider": effective,
                "effective_model": config["model"],
                "uses_default": not bool(assigned),
            }
        except LlmConfigError:
            result[role] = {
                "provider": assigned,
                "effective_provider": None,
                "effective_model": None,
                "uses_default": not bool(assigned),
            }
    return result


def mask_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "••••••••"
    return f"{api_key[:4]}{'•' * 8}{api_key[-4:]}"


def get_search_api_key(db: Session | None) -> str | None:
    config = get_search_config(db)
    return config["api_key"] if config["endpoint"] else None


def get_search_config(db: Session | None) -> dict[str, str | None]:
    if db is None:
        return {"api_key": None, "endpoint": None, "tool_name": DEFAULT_SEARCH_TOOL}
    row = db.get(LlmSettings, 1)
    if row is None or not row.encrypted_search_api_key:
        return {"api_key": None, "endpoint": row.search_endpoint if row else None, "tool_name": row.search_tool_name if row and row.search_tool_name else DEFAULT_SEARCH_TOOL}
    return {
        "api_key": decrypt_text(row.encrypted_search_api_key),
        "endpoint": row.search_endpoint,
        "tool_name": row.search_tool_name or DEFAULT_SEARCH_TOOL,
    }


def search_status(db: Session) -> dict:
    row = db.get(LlmSettings, 1)
    encrypted = row.encrypted_search_api_key if row else None
    try:
        api_key = decrypt_text(encrypted) if encrypted else None
        error = None
    except LlmConfigError:
        api_key = None
        error = "已保存的公开检索 Key 无法解密，请重新填写"
    return {
        "configured": bool(row and row.search_endpoint and not error),
        "api_key_masked": mask_key(api_key),
        "endpoint": row.search_endpoint if row else None,
        "tool_name": row.search_tool_name or DEFAULT_SEARCH_TOOL if row else DEFAULT_SEARCH_TOOL,
        "validation_message": error,
    }


def save_search_api_key(db: Session, api_key: str | None) -> dict:
    return save_search_config(db, api_key=api_key, endpoint=None, tool_name=None)


def save_search_config(
    db: Session,
    *,
    api_key: str | None,
    endpoint: str | None,
    tool_name: str | None,
) -> dict:
    value = api_key.strip() if api_key else ""
    row = db.get(LlmSettings, 1)
    if row is None:
        row = LlmSettings(id=1)
        db.add(row)
    row.encrypted_search_api_key = encrypt_text(value) if value else None
    if api_key is None and endpoint is None and tool_name is None:
        row.search_endpoint = None
        row.search_tool_name = DEFAULT_SEARCH_TOOL
    if endpoint is not None:
        row.search_endpoint = endpoint.strip() or None
    if tool_name is not None:
        row.search_tool_name = tool_name.strip() or DEFAULT_SEARCH_TOOL
    db.commit()
    db.refresh(row)
    return search_status(db)


def list_provider_status(db: Session) -> list[dict]:
    settings_row = db.get(LlmSettings, 1)
    default = settings_row.default_provider if settings_row else None
    rows = {row.provider: row for row in db.query(LlmProviderConfig).all()}
    result = []
    for provider in LLM_PROVIDER_NAMES:
        row = rows.get(provider)
        if row and row.enabled:
            model = row.model
            try:
                base_url = validate_base_url(row.base_url)
                base_url_error = None
            except LlmConfigError as exc:
                base_url = None
                base_url_error = str(exc)
            configured = bool(row.encrypted_api_key and row.model and not base_url_error)
            source = "database"
            stored_status = row.validation_status if row.validation_status in {"未验证", "已验证", "验证失败"} else "未验证"
            status = "验证失败" if base_url_error else stored_status
            message = base_url_error or row.validation_message
            try:
                masked = mask_key(decrypt_text(row.encrypted_api_key)) if row.encrypted_api_key else None
            except LlmConfigError:
                configured = False
                status = "验证失败"
                message = "已保存的 API Key 无法解密，请重新填写并保存"
                masked = None
            tested_at = row.last_tested_at
        else:
            model = ""
            configured = False
            source = None
            status = "未验证"
            message = None
            masked = None
            base_url = None
            tested_at = None
        result.append(
            {
                "name": provider,
                "label": PROVIDER_META[provider]["label"],
                "description": PROVIDER_META[provider]["description"],
                "model": model,
                "base_url": base_url,
                "api_key_masked": masked,
                "configured": configured,
                "source": source,
                "validation_status": status,
                "validation_message": message,
                "last_tested_at": tested_at,
                "is_default": provider == default or (default is None and configured and provider == resolve_provider(db)),
                "supports_tools": row.supports_tools if row and row.enabled else None,
                "supports_json": row.supports_json if row and row.enabled else None,
                "supports_streaming": row.supports_streaming if row and row.enabled else None,
                "supports_vision": row.supports_vision if row and row.enabled else None,
                "capability_checked_at": row.capability_checked_at if row and row.enabled else None,
            }
        )
    return result


def save_provider(
    db: Session,
    provider: str,
    *,
    api_key: str | None,
    model: str,
    base_url: str | None,
    validation_status: str = "未验证",
    validation_message: str | None = None,
) -> LlmProviderConfig:
    validate_provider(provider)
    if validation_status not in {"未验证", "已验证", "验证失败"}:
        validation_status = "未验证"
    model = model.strip()
    if not model:
        raise LlmConfigError("model 不能为空")
    base_url = validate_base_url(base_url)
    row = db.get(LlmProviderConfig, provider)
    if api_key is not None and api_key.strip():
        encrypted = encrypt_text(api_key.strip())
    elif row is not None and row.encrypted_api_key:
        try:
            decrypt_text(row.encrypted_api_key)
        except LlmConfigError:
            raise LlmConfigError(
                "已保存的 API Key 无法解密，请重新填写 API Key"
            ) from None
        encrypted = row.encrypted_api_key
    else:
        raise LlmConfigError("首次保存该模型时必须填写 API key")
    if row is None:
        row = LlmProviderConfig(provider=provider)
        db.add(row)
        connection_changed = True
    else:
        connection_changed = (
            bool(api_key is not None and api_key.strip())
            or model != row.model
            or base_url != row.base_url
        )
    row.encrypted_api_key = encrypted
    row.model = model
    row.base_url = base_url
    if connection_changed:
        row.validation_status = validation_status
        row.validation_message = validation_message
        # Changing a connection field invalidates the previous test result.
        row.last_tested_at = None
        row.supports_tools = None
        row.supports_json = None
        row.supports_streaming = None
        row.supports_vision = None
        row.capability_checked_at = None
    row.enabled = True
    db.commit()
    db.refresh(row)
    return row


def set_default_provider(db: Session, provider: str | None) -> None:
    if provider is not None:
        provider = resolve_provider(db, provider)
    row = db.get(LlmSettings, 1)
    if row is None:
        row = LlmSettings(id=1)
        db.add(row)
    row.default_provider = provider
    db.commit()


def touch_validation(
    db: Session,
    provider: str,
    status: str,
    message: str | None = None,
) -> None:
    row = db.get(LlmProviderConfig, provider)
    if row is None:
        return
    row.validation_status = status
    row.validation_message = message
    row.last_tested_at = datetime.now(timezone.utc)
    db.commit()


def touch_capabilities(
    db: Session,
    provider: str,
    *,
    supports_tools: bool | None,
    supports_json: bool | None,
    supports_streaming: bool | None,
    supports_vision: bool | None = None,
) -> None:
    row = db.get(LlmProviderConfig, provider)
    if row is None:
        return
    row.supports_tools = supports_tools
    row.supports_json = supports_json
    row.supports_streaming = supports_streaming
    row.supports_vision = supports_vision
    row.capability_checked_at = datetime.now(timezone.utc)
    db.commit()
