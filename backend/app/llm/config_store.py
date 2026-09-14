"""Provider configuration and encrypted task snapshots.

The process still supports the original .env based configuration.  A database
row is an explicit local-user override; deleting it returns the provider to
the .env value.  Secrets are never returned to API callers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.llm.prompts import PROMPT_VERSION
from app.llm.registry import PROVIDERS
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


def _fernet() -> Fernet:
    secret = settings.llm_config_secret.strip()
    if not secret:
        raise LlmConfigError("网页持久化配置需要设置 LLM_CONFIG_SECRET")
    raw = secret.encode("utf-8")
    # Accept a normal Fernet key, or deterministically derive one from the
    # operator-provided secret without ever logging the material.
    try:
        return Fernet(raw)
    except (ValueError, TypeError):
        import base64
        import hashlib

        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise LlmConfigError("模型配置密钥无法解密，请检查 LLM_CONFIG_SECRET") from exc


def _env_config(provider: str) -> dict:
    validate_provider(provider)
    config = dict(PROVIDERS[provider])
    try:
        config["api_base"] = validate_base_url(config.get("api_base"))
    except LlmConfigError as exc:
        # Keep a malformed legacy environment value from leaking through the
        # status endpoint; callers can present a safe actionable message.
        config["api_base"] = None
        config["_base_url_error"] = str(exc)
    return config


def get_effective_config(db: Session | None, provider: str) -> dict:
    """Return a LiteLLM-compatible config, preferring a database override."""

    validate_provider(provider)
    env_config = _env_config(provider)
    if db is None:
        if env_config.get("_base_url_error"):
            raise LlmConfigError(".env 中的 Base URL 无效，请修正后重启服务")
        return env_config
    row = db.get(LlmProviderConfig, provider)
    if row is None or not row.enabled:
        if env_config.get("_base_url_error"):
            raise LlmConfigError(".env 中的 Base URL 无效，请修正后重启服务")
        return env_config
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
    config = get_effective_config(db, provider)
    if overrides:
        config = {**config, **overrides}
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
    # A saved web configuration is an explicit user choice and should win over
    # legacy .env fallbacks until the user selects another default.  Sort by
    # updated_at so the most recently edited web provider is the natural choice
    # for an existing installation whose default_provider is still empty.
    if db is not None and not default:
        database_rows = (
            db.query(LlmProviderConfig)
            .filter(LlmProviderConfig.enabled.is_(True))
            .order_by(LlmProviderConfig.updated_at.desc())
            .all()
        )
        candidates.extend(row.provider for row in database_rows)
    # Keep the historical registry order for legacy .env-only installations.
    candidates.extend(
        name for name in PROVIDERS
        if name in LLM_PROVIDER_NAMES and name != default
    )
    candidates.extend(name for name in LLM_PROVIDER_NAMES if name != default and name not in candidates)
    for provider in candidates:
        if provider:
            try:
                config = get_effective_config(db, provider)
            except LlmConfigError:
                continue
            if config.get("api_key") and config.get("model"):
                return provider
    raise LlmConfigError("暂无可用分析模型，请先在设置页完成配置")


def mask_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "••••••••"
    return f"{api_key[:4]}{'•' * 8}{api_key[-4:]}"


def list_provider_status(db: Session) -> list[dict]:
    settings_row = db.get(LlmSettings, 1)
    default = settings_row.default_provider if settings_row else None
    rows = {row.provider: row for row in db.query(LlmProviderConfig).all()}
    result = []
    for provider in LLM_PROVIDER_NAMES:
        row = rows.get(provider)
        env = _env_config(provider)
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
            masked = mask_key(decrypt_text(row.encrypted_api_key)) if row.encrypted_api_key else None
            tested_at = row.last_tested_at
        else:
            model = env.get("model") or ""
            configured = bool(env.get("api_key") and model and not env.get("_base_url_error"))
            source = "env" if (env.get("api_key") and model) else None
            status = "验证失败" if env.get("_base_url_error") else "已验证" if configured else "未验证"
            message = env.get("_base_url_error")
            masked = mask_key(env.get("api_key"))
            base_url = env.get("api_base")
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
        encrypted = row.encrypted_api_key
    else:
        raise LlmConfigError("首次保存该模型时必须填写 API key")
    if row is None:
        row = LlmProviderConfig(provider=provider)
        db.add(row)
    row.encrypted_api_key = encrypted
    row.model = model
    row.base_url = base_url
    row.validation_status = validation_status
    row.validation_message = validation_message
    # Changing any connection field invalidates the previous test result.
    row.last_tested_at = None
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
