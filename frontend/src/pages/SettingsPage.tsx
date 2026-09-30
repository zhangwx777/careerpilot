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
import { StatusBadge } from "../components/DesignPrimitives";
import type { LlmRoleName, LlmRoles, ProviderConfigInput, ProviderOption, SearchConfig } from "../types";

type FormState = { api_key: string; model: string; base_url: string };
type UpdateCheck = { currentVersion: string; latestVersion: string; updateAvailable: boolean; installerAvailable: boolean };

declare global {
  interface Window {
    careerPilotUpdates?: {
      check: () => Promise<UpdateCheck>;
      install: () => Promise<void>;
    };
  }
}

const EMPTY_FORM: FormState = { api_key: "", model: "", base_url: "" };
const ROLE_LABELS: Record<LlmRoleName, string> = { interview: "面经分析", planner: "备战分析", briefing: "每日简报", vision: "图片识别" };

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
  return item.source === "database" ? "已保存" : "默认";
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
  const [searchConfig, setSearchConfig] = useState<SearchConfig | null>(null);
  const [searchKey, setSearchKey] = useState("");
  const [searchEndpoint, setSearchEndpoint] = useState("");
  const [searchToolName, setSearchToolName] = useState("search");
  const [searchSaving, setSearchSaving] = useState(false);
  const [roles, setRoles] = useState<LlmRoles | null>(null);
  const [roleSaving, setRoleSaving] = useState(false);
  const [updateCheck, setUpdateCheck] = useState<UpdateCheck | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [installingUpdate, setInstallingUpdate] = useState(false);
  const [updateError, setUpdateError] = useState("");
  const [updateMessage, setUpdateMessage] = useState("");

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
    api.search.get().then((config) => { setSearchConfig(config); setSearchEndpoint(config.endpoint ?? ""); setSearchToolName(config.tool_name); }).catch((reason: Error) => setError(reason.message));
    api.roles.get().then(setRoles).catch((reason: Error) => setError(reason.message));
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
      await api.providers.save(selectedProvider.name, payload());
      applyProviders(await api.providers.list());
      setForm((current) => ({ ...current, api_key: "" }));
      setMessage("配置已保存，重新打开页面后仍会保留。");
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
      setMessage("网页模型配置已删除。");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "配置删除失败"); }
  }

  async function saveSearch() {
    if (!searchEndpoint.trim() || !searchToolName.trim()) return;
    setSearchSaving(true); setError(""); setMessage("");
    try {
      const config = await api.search.save({ api_key: searchKey.trim(), endpoint: searchEndpoint.trim(), tool_name: searchToolName.trim() });
      setSearchConfig(config);
      setSearchKey("");
      setMessage(searchKey.trim() ? "联网工具配置已保存。" : "已启用匿名检索。未填写 Key 时按客户端 IP 使用 AnySearch 免费额度。");
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "公开检索配置保存失败"); }
    finally { setSearchSaving(false); }
  }

  async function removeSearch() {
    setSearchSaving(true); setError(""); setMessage("");
    try { setSearchConfig(await api.search.remove()); setSearchKey(""); setSearchEndpoint(""); setSearchToolName("search"); setMessage("联网工具配置已删除，业务将只使用本地资料。"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "公开检索配置删除失败"); }
    finally { setSearchSaving(false); }
  }

  async function saveRoles() {
    if (!roles) return;
    setRoleSaving(true); setError(""); setMessage("");
    try { setRoles(await api.roles.save(Object.fromEntries(Object.entries(roles.roles).map(([role, item]) => [role, item.provider])) as Record<LlmRoleName, string | null>)); setMessage("模型分工已保存。"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "角色分工保存失败"); }
    finally { setRoleSaving(false); }
  }

  async function checkForUpdates() {
    if (!window.careerPilotUpdates) return;
    setCheckingUpdate(true);
    setUpdateError("");
    setUpdateMessage("");
    try {
      const result = await window.careerPilotUpdates.check();
      setUpdateCheck(result);
      setUpdateMessage(result.updateAvailable
        ? result.installerAvailable ? `发现新版本 v${result.latestVersion}。` : `发现新版本 v${result.latestVersion}，但 Release 中没有安装包。`
        : `当前已是最新版本 v${result.currentVersion}。`);
    } catch (reason) {
      setUpdateError(reason instanceof Error ? reason.message : "检查更新失败");
    } finally {
      setCheckingUpdate(false);
    }
  }

  async function installUpdate() {
    if (!window.careerPilotUpdates) return;
    setInstallingUpdate(true);
    setUpdateError("");
    setUpdateMessage("正在下载并启动安装器…");
    try {
      await window.careerPilotUpdates.install();
    } catch (reason) {
      setUpdateError(reason instanceof Error ? reason.message : "下载或启动安装器失败");
      setInstallingUpdate(false);
    }
  }

  if (loading) {
    return <section><div className="page-heading"><div><span className="eyebrow">工作区设置</span><h1>模型设置</h1></div></div><div className="panel loading-state" aria-label="正在读取模型配置"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></div></section>;
  }

  return (
    <section>
      <div className="page-heading settings-heading">
        <div>
          <span className="eyebrow">工作区设置</span>
          <h1>模型设置</h1>
          <p>在这里管理模型连接和各项功能使用的模型。</p>
        </div>
        <div className="settings-security-note"><LockKey size={18} /><span>密钥只回传掩码，不写入浏览器存储。</span></div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}
      {message && <div className="notice success" role="status">{message}</div>}

      <div className="settings-layout">
        {roles && <details className="panel settings-disclosure" aria-label="使用场景设置">
          <summary><span><span className="eyebrow">使用场景</span><strong>模型分工</strong></span><span className="settings-disclosure-hint">点击展开</span></summary>
          <section className="role-assignment">
            <div className="settings-toolbar"><div><span className="eyebrow">使用场景</span><h2>模型分工</h2></div><button className="button primary compact-button" type="button" onClick={() => void saveRoles()} disabled={roleSaving}>{roleSaving ? "保存中…" : "保存分工"}</button></div>
            <p className="section-help">可以为不同功能指定模型；留空时使用默认模型。</p>
            <div className="role-grid">
              {(Object.keys(ROLE_LABELS) as LlmRoleName[]).map((role) => {
                const item = roles.roles[role];
                return <label className="role-card" key={role}><span>{ROLE_LABELS[role]}</span><select value={item.provider ?? ""} onChange={(event) => setRoles((current) => current ? { ...current, roles: { ...current.roles, [role]: { ...item, provider: event.target.value || null } } } : current)}><option value="">使用全局默认</option>{providers.filter((provider) => provider.configured).map((provider) => <option value={provider.name} key={provider.name}>{provider.label} · {provider.model}</option>)}</select><small>{item.effective_provider ? `当前生效：${item.effective_provider} · ${item.effective_model}` : "未找到可用模型"}</small></label>;
              })}
            </div>
          </section>
        </details>}
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
              <StatusBadge tone={selectedProvider.configured ? "ready" : "warning"}>
                {selectedProvider.validation_status === "已验证" ? <CheckCircle size={15} weight="fill" /> : <WarningCircle size={15} weight="fill" />}
                {statusLabel(selectedProvider)}
              </StatusBadge>
            </div>

            <div className="provider-meta-strip">
              <span>来源：{sourceLabel(selectedProvider)}</span>
              <span>{selectedProvider.api_key_masked ? `密钥 ${selectedProvider.api_key_masked}` : "未保存密钥"}</span>
              <span>文本：{selectedProvider.configured ? "可用" : "未配置"}</span>
              <span>工具：{selectedProvider.supports_tools === true ? "可用" : selectedProvider.supports_tools === false ? "不支持" : "未检测"}</span>
              <span>图片：{selectedProvider.supports_vision === true ? "可用" : selectedProvider.supports_vision === false ? "不支持" : "未检测"}</span>
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
              {selectedProvider.source === "database" && <button className="button ghost danger-button" type="button" onClick={() => void remove()}><Trash size={16} />删除已保存配置</button>}
            </div>
          </div>
        )}
      </div>

      <details className="panel settings-disclosure search-settings-disclosure">
        <summary><span><span className="eyebrow">公开资料补充</span><strong>公开检索</strong></span><StatusBadge tone={searchConfig?.configured ? "ready" : "neutral"}>{searchConfig?.configured ? (searchConfig.api_key_masked ? "已配置 Key" : "匿名可用") : "未配置"}</StatusBadge></summary>
        <div className="search-settings-card">
          <p className="settings-help">配置联网地址和工具名后，面经分析和每日简报可补充公开资料。API Key 可留空以使用 AnySearch 匿名额度；配置 Key 可使用对应账户额度。</p>
          {searchConfig?.api_key_masked && <div className="provider-meta-strip"><span>当前密钥：{searchConfig.api_key_masked}</span></div>}
          <div className="settings-form-grid">
            <label className="field-block"><span>联网工具 API 地址</span><input type="url" value={searchEndpoint} onChange={(event) => setSearchEndpoint(event.target.value)} placeholder="https://example.com/mcp" /></label>
            <label className="field-block"><span>搜索工具名称</span><input value={searchToolName} onChange={(event) => setSearchToolName(event.target.value)} placeholder="search" /></label>
          </div>
          <label className="field-block"><span>联网工具 API Key（可选）</span><input type="password" value={searchKey} onChange={(event) => setSearchKey(event.target.value)} placeholder="留空使用匿名额度" autoComplete="new-password" /></label>
          <div className="provider-actions"><button className="button primary" type="button" onClick={() => void saveSearch()} disabled={searchSaving || !searchEndpoint.trim() || !searchToolName.trim()}><FloppyDisk size={17} />{searchSaving ? "保存中…" : "保存联网工具"}</button>{searchConfig?.configured && <button className="button ghost danger-button" type="button" onClick={() => void removeSearch()} disabled={searchSaving}><Trash size={16} />删除配置</button>}</div>
        </div>
      </details>

      {window.careerPilotUpdates && <div className="panel update-settings-card">
        <div className="settings-toolbar">
          <div><span className="eyebrow">应用维护</span><h2>软件更新</h2></div>
          {updateCheck && <span className="settings-toolbar-hint">当前版本 v{updateCheck.currentVersion}</span>}
        </div>
        <p className="section-help">检查 GitHub Releases；有新版本时下载并启动安装器。</p>
        <div className="provider-actions">
          <button className="button" type="button" onClick={() => void checkForUpdates()} disabled={checkingUpdate || installingUpdate}>
            <ArrowClockwise size={17} />{checkingUpdate ? "检查中…" : "检查更新"}
          </button>
          {updateCheck?.updateAvailable && updateCheck.installerAvailable && <button className="button primary" type="button" onClick={() => void installUpdate()} disabled={installingUpdate || checkingUpdate}>
            {installingUpdate ? "下载并启动中…" : `下载并安装 v${updateCheck.latestVersion}`}
          </button>}
        </div>
        {updateMessage && <p className="section-help" role="status">{updateMessage}</p>}
        {updateError && <div className="notice error" role="alert">{updateError}</div>}
      </div>}

      <div className="settings-local-note"><LockKey size={16} /><span>配置仅保存在本机，不会写入浏览器存储。</span></div>
    </section>
  );
}
