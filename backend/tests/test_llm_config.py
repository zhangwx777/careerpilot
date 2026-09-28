import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from unittest.mock import patch

from cryptography.fernet import Fernet
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
    get_search_api_key,
    list_provider_status,
    resolve_provider,
    save_provider,
    save_search_config,
    save_search_api_key,
    search_status,
    set_default_provider,
    snapshot_for,
    touch_validation,
    validate_base_url,
)
from app.llm.provider import LlmCallError
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
        self.secret_dir = TemporaryDirectory()
        self.secret = patch(
            "app.llm.config_store.CONFIG_SECRET_FILE",
            Path(self.secret_dir.name) / ".llm_config_secret",
        )
        self.secret.start()

    def tearDown(self):
        self.db.query(LlmProviderConfig).delete()
        self.db.query(LlmSettings).delete()
        self.db.commit()
        self.db.close()
        self.secret.stop()
        self.secret_dir.cleanup()

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

    def test_saved_deepseek_config_survives_a_new_database_session(self):
        save_provider(
            self.db,
            "deepseek",
            api_key="persistent-key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )

        fresh_session = Session(self.engine)
        try:
            self.assertEqual(
                get_effective_config(fresh_session, "deepseek"),
                {
                    "api_key": "persistent-key",
                    "api_base": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                },
            )
            status = next(item for item in list_provider_status(fresh_session) if item["name"] == "deepseek")
            self.assertTrue(status["configured"])
        finally:
            fresh_session.close()

    def test_search_key_is_encrypted_masked_and_deletable(self):
        status = save_search_config(
            self.db,
            api_key="search-secret-key",
            endpoint="https://search.example.test/mcp",
            tool_name="web_search",
        )
        self.assertTrue(status["configured"])
        self.assertNotIn("search-secret-key", status["api_key_masked"])
        self.assertEqual(get_search_api_key(self.db), "search-secret-key")
        self.assertEqual(status["endpoint"], "https://search.example.test/mcp")
        self.assertEqual(status["tool_name"], "web_search")
        self.assertEqual(search_status(self.db)["api_key_masked"], status["api_key_masked"])
        deleted = save_search_api_key(self.db, None)
        self.assertFalse(deleted["configured"])
        self.assertIsNone(get_search_api_key(self.db))

    def test_provider_list_stays_usable_when_stored_key_cannot_be_decrypted(self):
        save_provider(
            self.db,
            "openai",
            api_key="old-secret-key",
            model="openai/gpt-4o-mini",
            base_url=None,
        )
        Path(self.secret_dir.name, ".llm_config_secret").write_bytes(Fernet.generate_key())

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                response = client.get("/api/providers")
            self.assertEqual(response.status_code, 200, response.text)
            status = next(item for item in response.json() if item["name"] == "openai")
        finally:
            app.dependency_overrides.clear()

        self.assertFalse(status["configured"])
        self.assertIsNone(status["api_key_masked"])
        self.assertEqual(status["validation_status"], "验证失败")
        self.assertIn("重新填写", status["validation_message"])

    def test_decrypt_tries_legacy_install_secret_after_data_dir_move(self):
        legacy_secret = Path(self.secret_dir.name, "legacy.llm_config_secret")
        legacy_key = Fernet.generate_key()
        legacy_secret.write_bytes(legacy_key)
        token = Fernet(legacy_key).encrypt(b"migrated-secret").decode("ascii")
        Path(self.secret_dir.name, ".llm_config_secret").write_bytes(Fernet.generate_key())

        with patch(
            "app.llm.config_store.LEGACY_CONFIG_SECRET_FILES",
            (legacy_secret,),
            create=True,
        ):
            from app.llm.config_store import decrypt_text

            self.assertEqual(decrypt_text(token), "migrated-secret")

    def test_resaving_unreadable_provider_requires_a_replacement_key(self):
        save_provider(
            self.db,
            "openai",
            api_key="old-secret-key",
            model="openai/gpt-4o-mini",
            base_url=None,
        )
        Path(self.secret_dir.name, ".llm_config_secret").write_bytes(Fernet.generate_key())

        with self.assertRaisesRegex(LlmConfigError, "重新填写 API Key"):
            save_provider(
                self.db,
                "openai",
                api_key=None,
                model="openai/gpt-4o-mini",
                base_url=None,
            )

    def test_resaving_unchanged_connection_keeps_validation_result(self):
        save_provider(
            self.db,
            "deepseek",
            api_key="key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        touch_validation(self.db, "deepseek", "已验证", "连接成功")
        row = save_provider(
            self.db,
            "deepseek",
            api_key=None,
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        self.assertEqual(row.validation_status, "已验证")
        self.assertEqual(row.validation_message, "连接成功")
        self.assertIsNotNone(row.last_tested_at)

    def test_changing_connection_field_invalidates_validation_result(self):
        save_provider(
            self.db,
            "deepseek",
            api_key="key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        touch_validation(self.db, "deepseek", "已验证", "连接成功")
        row = save_provider(
            self.db,
            "deepseek",
            api_key=None,
            model="deepseek-reasoner",
            base_url="https://api.deepseek.com",
        )
        self.assertEqual(row.validation_status, "未验证")
        self.assertIsNone(row.last_tested_at)

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

    def test_web_configuration_is_implicit_default(self):
        save_provider(self.db, "deepseek", api_key="key", model="deepseek/chat", base_url=None)
        self.assertEqual(resolve_provider(self.db), "deepseek")

    def test_role_mapping_round_trips_and_falls_back_to_default(self):
        from app.llm.config_store import get_role_status, save_role_providers

        save_provider(self.db, "deepseek", api_key="key", model="deepseek/chat", base_url=None)
        save_provider(self.db, "anthropic", api_key="key", model="anthropic/claude", base_url=None)
        set_default_provider(self.db, "deepseek")
        saved = save_role_providers(self.db, {"interview": "anthropic", "planner": None, "briefing": None, "vision": None})
        self.assertEqual(saved["interview"], "anthropic")
        self.assertEqual(get_role_status(self.db)["interview"]["effective_provider"], "anthropic")
        self.assertTrue(get_role_status(self.db)["planner"]["uses_default"])

    def test_role_mapping_rejects_unconfigured_provider(self):
        from app.llm.config_store import save_role_providers

        with self.assertRaises(LlmConfigError):
            save_role_providers(self.db, {"interview": "deepseek", "planner": None, "briefing": None, "vision": None})

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

    def test_unconfigured_web_provider_is_not_available(self):
        status = next(item for item in list_provider_status(self.db) if item["name"] == "openai")
        self.assertFalse(status["configured"])
        self.assertIsNone(status["source"])
        with self.assertRaises(LlmConfigError):
            get_effective_config(self.db, "openai")

    def test_api_masks_keys_and_supports_default_selection(self):
        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
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
            with patch("app.api.chat", return_value="{\"ok\":true}") as chat_mock, TestClient(app) as client:
                success = client.post(
                    "/api/llm/providers/openai/test",
                    json={"model": "openai/gpt", "api_key": "temporary-key", "base_url": None},
                )
                self.assertEqual(success.status_code, 200, success.text)
                self.assertTrue(success.json()["ok"])
                self.assertEqual(chat_mock.call_args.kwargs["generation"], "structured")
                self.assertEqual(
                    chat_mock.call_args.kwargs["response_format"],
                    {"type": "json_object"},
                )

            with patch("app.api.chat", side_effect=LlmCallError("timeout")), TestClient(app) as client:
                failure = client.post(
                    "/api/llm/providers/openai/test",
                    json={"model": "openai/gpt", "api_key": "temporary-key", "base_url": None},
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
            with patch("app.llm.config_store.urlopen", return_value=FakeResponse()) as request:
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
            with patch(
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
