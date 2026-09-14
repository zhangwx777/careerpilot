import {
  ArrowClockwise,
  CheckCircle,
  Eye,
  EyeSlash,
  FloppyDisk,
  LockKey,
  PlugsConnected,
  Star,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import type { ProviderConfigInput, ProviderOption } from "../types";

type FormState = { api_key: string; model: string; base_url: string };
const EMPTY_FORM: FormState = { api_key: "", model: "", base_url: "" };

function formFromProvider(item: ProviderOption): FormState {
  return { api_key: "", model: item.model, base_url: item.base_url ?? "" };
}

function statusLabel(item: ProviderOption) {
  if (!item.configured) return "未配置";
  if (item.validation_status === "验证失败") return "验证失败";
  if (item.validation_status === "未验证") return "待验证";
  return "已验证";
}

function sourceLabel(item: ProviderOption) {
  return item.source === "database" ? "网页" : item.source === "env" ? ".env" : "—";
}

export function SettingsPage() {
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [selected, setSelected] = useState("openai");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selectedProvider = useMemo(
    () => providers.find((item) => item.name === selected) ?? providers[0],
    [providers, selected],
  );

  function applyProviders(items: ProviderOption[]) {
    setProviders(items);
    const next = items.find((item) => item.name === selected) ?? items[0];
    if (next) {
      setSelected(next.name);
      setForm(formFromProvider(next));
    }
  }

  useEffect(() => {
    api.providers.list()
      .then(applyProviders)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  function chooseProvider(name: string) {
    const item = providers.find((candidate) => candidate.name === name);
    if (!item) return;
    setSelected(name);
    setForm(formFromProvider(item));
    setAvailableModels([]);
    setShowKey(false);
    setMessage("");
    setError("");
  }

  function input(name: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function payload(): ProviderConfigInput {
    return {
      api_key: form.api_key.trim() || undefined,
      model: form.model.trim(),
      base_url: form.base_url.trim() || null,
    };
  }

  async function loadModels() {
    if (!selectedProvider) return;
    setLoadingModels(true); setError(""); setMessage("");
    try {
      const result = await api.providers.models(selectedProvider.name, {
        api_key: form.api_key.trim() || undefined,
        base_url: form.base_url.trim() || null,
      });
      setAvailableModels(result.models);
      if (!result.models.includes(form.model)) setForm((current) => ({ ...current, model: "" }));
      setMessage(`已读取 ${result.models.length} 个可用模型。`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取模型目录失败");
    } finally { setLoadingModels(false); }
  }

  async function save() {
    if (!selectedProvider) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const saved = await api.providers.save(selectedProvider.name, payload());
      setProviders((current) => current.map((item) => item.name === saved.name ? saved : item));
      setForm((current) => ({ ...current, api_key: "" }));
      setMessage("配置已保存。密钥只保存在服务端密文中。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "配置保存失败");
    } finally { setSaving(false); }
  }

  async function test() {
    if (!selectedProvider) return;
    setTesting(true); setError(""); setMessage("");
    try {
      const result = await api.providers.test(selectedProvider.name, payload());
      if (result.ok) setMessage(`${result.message}${result.latency_ms ? ` · ${result.latency_ms} ms` : ""}`);
      else setError(result.message);
      applyProviders(await api.providers.list());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接测试失败");
    } finally { setTesting(false); }
  }

  async function setDefault() {
    if (!selectedProvider) return;
    setError(""); setMessage("");
    try {
      applyProviders(await api.providers.setDefault(selectedProvider.name));
      setMessage("默认模型已更新。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "默认模型更新失败"); }
  }

  async function remove() {
    if (!selectedProvider || selectedProvider.source !== "database") return;
    setError(""); setMessage("");
    try {
      applyProviders(await api.providers.remove(selectedProvider.name));
      setMessage("网页覆盖配置已删除；若 .env 中有配置，将自动回退到 .env。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "配置删除失败"); }
  }

  if (loading) {
    return <section><div className="page-heading"><div><span className="eyebrow">工作区设置</span><h1>模型配置</h1></div></div><div className="panel loading-state" aria-label="正在读取模型配置"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div></section>;
  }

  return (
    <section>
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">工作区设置 · 本机单用户</span>
          <h1>模型配置</h1>
          <p>在同一处管理多个模型连接；任务创建时会固定当时的配置。</p>
        </div>
        <div className="settings-security-note"><LockKey size={18} /><span>密钥只回传掩码，不写入浏览器存储。</span></div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}
      {message && <div className="notice success" role="status">{message}</div>}

      <div className="settings-layout">
        <div className="panel provider-index" aria-label="模型连接配置">
          <div className="settings-toolbar">
            <div><span className="eyebrow">连接清单</span><h2>选择要编辑的模型</h2></div>
            <span className="settings-toolbar-hint">可同时保存多家</span>
          </div>
          <div className="provider-table" role="list">
            {providers.map((item) => (
              <button key={item.name} className={`provider-row${item.name === selectedProvider?.name ? " active" : ""}`} onClick={() => chooseProvider(item.name)} type="button" role="listitem">
                <span className={`provider-status-dot ${item.configured ? "ready" : ""}`} aria-hidden="true" />
                <span className="provider-row-name"><strong>{item.label}</strong><small>{item.model || "未填写模型"}</small></span>
                <span className="provider-row-source">{sourceLabel(item)}</span>
                <span className={`provider-row-status ${item.configured ? "ready" : ""}`}>{statusLabel(item)}</span>
                {item.is_default && <Star size={16} weight="fill" aria-label="默认模型" />}
              </button>
            ))}
          </div>
        </div>

        {selectedProvider && (
          <div className="panel provider-editor">
            <div className="provider-editor-heading">
              <div><span className="eyebrow">{selectedProvider.label}</span><h2>连接参数</h2></div>
              <span className={`status-badge ${selectedProvider.configured ? "ready" : ""}`}>
                {selectedProvider.validation_status === "已验证" ? <CheckCircle size={15} weight="fill" /> : <WarningCircle size={15} weight="fill" />}
                {statusLabel(selectedProvider)}
              </span>
            </div>

            <div className="provider-meta-strip">
              <span>来源：{sourceLabel(selectedProvider)}</span>
              <span>{selectedProvider.api_key_masked ? `密钥 ${selectedProvider.api_key_masked}` : "未保存密钥"}</span>
              {selectedProvider.last_tested_at && <span>测试于 {new Date(selectedProvider.last_tested_at).toLocaleString("zh-CN")}</span>}
              {selectedProvider.validation_message && <span>{selectedProvider.validation_message}</span>}
            </div>

            <div className="settings-fields">
              <label className="field-block"><span>API Key</span><div className="secret-input"><input type={showKey ? "text" : "password"} value={form.api_key} onChange={(event) => input("api_key", event.target.value)} placeholder={selectedProvider.api_key_masked ? "留空以继续使用已保存的密钥" : "粘贴 API Key"} autoComplete="new-password" /><button type="button" onClick={() => setShowKey((value) => !value)} aria-label={showKey ? "隐藏 API Key" : "显示 API Key"}>{showKey ? <EyeSlash size={18} /> : <Eye size={18} />}</button></div><small>保存后不会再次读取完整密钥。</small></label>
              <label className="field-block"><span>Model</span><div className="model-picker"><select value={form.model} onChange={(event) => input("model", event.target.value)} disabled={loadingModels} required><option value="">{availableModels.length ? "选择可用模型" : "先读取可用模型"}</option>{form.model && !availableModels.includes(form.model) && <option value={form.model}>{form.model}</option>}{availableModels.map((model) => <option key={model} value={model}>{model}</option>)}</select><button className="button ghost" type="button" onClick={() => void loadModels()} disabled={loadingModels || saving || testing}><ArrowClockwise size={16} />{loadingModels ? "读取中…" : "读取模型"}</button></div><small>根据当前 API Key 和 Base URL 从供应商读取。</small></label>
              <label className="field-block"><span>Base URL <em>可选</em></span><input value={form.base_url} onChange={(event) => input("base_url", event.target.value)} placeholder="例如：https://api.example.com/v1" inputMode="url" /><small>填写 API 根路径，不要填 /chat/completions。</small></label>
            </div>

            <div className="provider-actions">
              <button className="button" type="button" onClick={() => void test()} disabled={testing || saving}><PlugsConnected size={17} />{testing ? "测试中…" : "测试连接"}</button>
              <button className="button primary" type="button" onClick={() => void save()} disabled={saving || testing || !form.model.trim()}><FloppyDisk size={17} />{saving ? "保存中…" : "保存配置"}</button>
            </div>
            <div className="provider-secondary-actions">
              <button className="button ghost" type="button" onClick={() => void setDefault()} disabled={!selectedProvider.configured || selectedProvider.is_default}><Star size={16} />{selectedProvider.is_default ? "当前默认模型" : "设为默认"}</button>
              {selectedProvider.source === "database" && <button className="button ghost danger-button" type="button" onClick={() => void remove()}><Trash size={16} />删除网页配置</button>}
            </div>
          </div>
        )}
      </div>

      <div className="panel settings-callout"><LockKey size={20} /><div><strong>本机安全边界</strong><p>当前版本按单用户本地工作区设计。请勿把服务端口直接暴露到公网；多人使用前应先加入登录和按用户隔离。</p></div></div>
    </section>
  );
}
