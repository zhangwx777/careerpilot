import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base
from app.db import get_db
from app.main import app
from app.llm.config_store import (
    LlmConfigError,
    _model_endpoint_candidates,
    config_from_snapshot,
    get_effective_config,
    list_provider_status,
    resolve_provider,
    save_provider,
    set_default_provider,
    snapshot_for,
    validate_base_url,
)
from app.llm.registry import PROVIDERS
from app.llm.provider import LlmCallError
from app.config import settings
from app.models import LlmProviderConfig, LlmSettings


class LlmConfigTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine, tables=[LlmProviderConfig.__table__, LlmSettings.__table__])

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.db = Session(self.engine)
        self.secret = patch.object(settings, "llm_config_secret", "unit-test-secret")
        self.secret.start()
        self.providers = patch.dict(
            PROVIDERS,
            {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            },
            clear=True,
        )
        self.providers.start()

    def tearDown(self):
        self.db.query(LlmProviderConfig).delete()
        self.db.query(LlmSettings).delete()
        self.db.commit()
        self.db.close()
        self.providers.stop()
        self.secret.stop()

    def test_database_override_is_encrypted_and_round_trips(self):
        row = save_provider(
            self.db,
            "deepseek",
            api_key="db-secret-key",
            model="deepseek/deepseek-chat",
            base_url="https://example.test/v1",
        )
        self.assertNotIn("db-secret-key", row.encrypted_api_key)
        self.assertEqual(
            get_effective_config(self.db, "deepseek"),
            {"api_key": "db-secret-key", "api_base": "https://example.test/v1", "model": "deepseek/deepseek-chat"},
        )

    def test_task_snapshot_survives_later_provider_change(self):
        save_provider(self.db, "openai", api_key="first-key", model="openai/one", base_url=None)
        token = snapshot_for(self.db, "openai")
        save_provider(self.db, "openai", api_key="second-key", model="openai/two", base_url=None)
        self.assertEqual(config_from_snapshot(token, self.db, "openai")["api_key"], "first-key")

    def test_default_provider_prefers_explicit_setting(self):
        save_provider(self.db, "deepseek", api_key="key", model="deepseek/chat", base_url=None)
        set_default_provider(self.db, "deepseek")
        statuses = {item["name"]: item for item in list_provider_status(self.db)}
        self.assertTrue(statuses["deepseek"]["is_default"])
        self.assertFalse(statuses["openai"]["is_default"])

    def test_web_configuration_wins_implicit_env_default(self):
        save_provider(self.db, "deepseek", api_key="key", model="deepseek/chat", base_url=None)
        self.assertEqual(resolve_provider(self.db), "deepseek")

    def test_base_url_rejects_credentials_and_non_http_schemes(self):
        with self.assertRaises(LlmConfigError):
            validate_base_url("file:///tmp/model")
        with self.assertRaises(LlmConfigError):
            validate_base_url("https://user:pass@example.test/v1")

    def test_model_catalogue_accepts_root_or_chat_completion_base_urls(self):
        self.assertEqual(
            _model_endpoint_candidates("openai", "https://gateway.test/v1"),
            ["https://gateway.test/v1/models"],
        )
        self.assertEqual(
            _model_endpoint_candidates("anthropic", "https://gateway.test"),
            ["https://gateway.test/models", "https://gateway.test/v1/models"],
        )
        self.assertEqual(
            _model_endpoint_candidates("openai", "https://gateway.test/v1/chat/completions"),
            ["https://gateway.test/v1/models"],
        )

    def test_invalid_legacy_base_url_is_not_reported_as_configured(self):
        with patch.dict(
            PROVIDERS,
            {"openai": {"api_key": "env-openai", "api_base": "file:///secret", "model": "openai/gpt"}},
            clear=False,
        ):
            status = next(item for item in list_provider_status(self.db) if item["name"] == "openai")
            self.assertFalse(status["configured"])
            self.assertEqual(status["validation_status"], "验证失败")
            with self.assertRaises(LlmConfigError):
                get_effective_config(self.db, "openai")

    def test_api_masks_keys_and_supports_default_selection(self):
        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with patch("app.llm.config_store.PROVIDERS", {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            }), TestClient(app) as client:
                saved = client.put(
                    "/api/llm/providers/deepseek",
                    json={"api_key": "api-secret", "model": "deepseek/chat", "base_url": None},
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertNotIn("api-secret", saved.text)
                self.assertEqual(saved.json()["api_key_masked"], "api-••••••••cret")
                listed = client.get("/api/providers")
                self.assertEqual(listed.status_code, 200, listed.text)
                self.assertNotIn("api-secret", listed.text)
                selected = client.put("/api/llm/default", json={"provider": "deepseek"})
                self.assertEqual(selected.status_code, 200, selected.text)
                self.assertTrue(next(item for item in selected.json() if item["name"] == "deepseek")["is_default"])
        finally:
            app.dependency_overrides.clear()

    def test_connection_test_reports_success_and_safe_failure(self):
        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with patch("app.llm.config_store.PROVIDERS", {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            }), patch("app.api.chat", return_value="{\"ok\":true}") as chat_mock, TestClient(app) as client:
                success = client.post(
                    "/api/llm/providers/openai/test",
                    json={"model": "openai/gpt", "api_key": "temporary-key"},
                )
                self.assertEqual(success.status_code, 200, success.text)
                self.assertTrue(success.json()["ok"])
                self.assertEqual(chat_mock.call_args.kwargs["generation"], "structured")
                self.assertEqual(
                    chat_mock.call_args.kwargs["response_format"],
                    {"type": "json_object"},
                )

            with patch("app.llm.config_store.PROVIDERS", {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            }), patch("app.api.chat", side_effect=LlmCallError("timeout")), TestClient(app) as client:
                failure = client.post(
                    "/api/llm/providers/openai/test",
                    json={"model": "openai/gpt", "api_key": "temporary-key"},
                )
                self.assertEqual(failure.status_code, 200, failure.text)
                self.assertFalse(failure.json()["ok"])
                self.assertIn("超时", failure.json()["message"])
                self.assertNotIn("temporary-key", failure.text)
        finally:
            app.dependency_overrides.clear()

    def test_model_catalogue_reads_ids_without_echoing_key(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"data":[{"id":"openai/gpt-4o-mini"},{"id":"openai/gpt-4o"}]}'

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with patch("app.llm.config_store.PROVIDERS", {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            }), patch("app.llm.config_store.urlopen", return_value=FakeResponse()) as request:
                response = TestClient(app).post(
                    "/api/llm/providers/openai/models",
                    json={"api_key": "temporary-key", "base_url": "https://api.example.test/v1"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["models"], ["openai/gpt-4o", "openai/gpt-4o-mini"])
                self.assertNotIn("temporary-key", response.text)
                self.assertTrue(request.called)
                self.assertEqual(request.call_args.args[0].headers["User-agent"], "qiuzhao-agent/0.1")
        finally:
            app.dependency_overrides.clear()

    def test_model_catalogue_retries_v1_path_after_root_404(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"data":[{"id":"gateway/model"}]}'

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with patch("app.llm.config_store.PROVIDERS", {
                "openai": {"api_key": "env-openai", "api_base": None, "model": "openai/gpt"},
                "anthropic": {"api_key": "", "api_base": None, "model": ""},
                "deepseek": {"api_key": "", "api_base": None, "model": ""},
                "qwen": {"api_key": "", "api_base": None, "model": ""},
            }), patch(
                "app.llm.config_store.urlopen",
                side_effect=[HTTPError("https://gateway.test/models", 404, "missing", {}, None), FakeResponse()],
            ) as request:
                response = TestClient(app).post(
                    "/api/llm/providers/openai/models",
                    json={"api_key": "temporary-key", "base_url": "https://gateway.test"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["models"], ["gateway/model"])
                self.assertEqual(request.call_count, 2)
                self.assertTrue(request.call_args_list[1].args[0].full_url.endswith("/v1/models"))
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
