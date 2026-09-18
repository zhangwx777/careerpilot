import { ClockCounterClockwise, FileText, Sparkle, Trash, UploadSimple } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { loadDraft, loadSessionId, saveDraft, saveSessionId, clearDraft } from "../drafts";
import { formatDateTime } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Application, PlannerReport, PlannerSession, PreparationTask, ProviderOption, ResumeProfile } from "../types";

const plannerDraftKey = "qiuzhao-agent:planner-draft";
const activePlannerSessionKey = "qiuzhao-agent:planner-active-session";
type PlannerDraft = { applicationId: number; provider: string; fileName: string };

function isReport(value: PlannerSession["draft_payload"]): value is PlannerReport {
  return Boolean(value && "actions" in value);
}

export function PlannerPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sessionId = id ? Number(id) : null;
  const draft = loadDraft<PlannerDraft>(window.localStorage, plannerDraftKey, { applicationId: 0, provider: "", fileName: "" });
  const [applications, setApplications] = useState<Application[]>([]);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [applicationId, setApplicationId] = useState(draft.applicationId);
  const [provider, setProvider] = useState(draft.provider);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [fileName, setFileName] = useState(draft.fileName);
  const [session, setSession] = useState<PlannerSession | null>(null);
  const [history, setHistory] = useState<PlannerSession[]>([]);
  const [sessionTasks, setSessionTasks] = useState<PreparationTask[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [confirmingResumeDelete, setConfirmingResumeDelete] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.applications.list({ page_size: 100 }).then((result) => { if (!cancelled) setApplications(result.items); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    api.providers.list().then((result) => { if (!cancelled) { const configured = result.filter((item) => item.configured); setProviders(configured); setProvider((current) => configured.some((item) => item.name === current) ? current : configured.find((item) => item.is_default)?.name ?? configured[0]?.name ?? ""); } }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    api.planner.resume().then((result) => { if (!cancelled) { setProfile(result); setFileName(result.file_name ?? ""); } }).catch(() => { if (!cancelled) { setProfile(null); setFileName(""); } });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => { saveDraft(window.localStorage, plannerDraftKey, { applicationId, provider, fileName }); }, [applicationId, provider, fileName]);
  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      const active = loadSessionId(window.localStorage, activePlannerSessionKey);
      api.planner.sessions().then((items) => {
        setHistory(items);
        const isResumable = (item: PlannerSession) => item.status === "生成中" || item.status === "待确认";
        const resumable = items.find((item) => item.id === active && isResumable(item)) ?? items.find(isResumable);
        if (resumable) {
          saveSessionId(window.localStorage, activePlannerSessionKey, resumable.id);
          navigate(`/planner/${resumable.id}`, { replace: true });
        } else {
          clearDraft(window.localStorage, activePlannerSessionKey);
        }
      }).catch((reason: Error) => setError(reason.message));
      return;
    }
    setSession(null);
    let cancelled = false;
    const refresh = () => api.planner.session(sessionId).then((result) => {
      if (cancelled) return;
      setSession(result);
      setApplicationId(result.application_id);
      if (result.status === "生成中" || result.status === "待确认") {
        saveSessionId(window.localStorage, activePlannerSessionKey, result.id);
      } else clearDraft(window.localStorage, activePlannerSessionKey);
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    refresh();
    return () => { cancelled = true; };
  }, [navigate, sessionId]);

  useEffect(() => {
    if (!sessionId || session?.status !== "已完成") {
      setSessionTasks([]);
      return;
    }
    api.planner.tasks({ application_id: session.application_id, page_size: 100, include_deferred: true })
      .then((result) => setSessionTasks(result.items.filter((task) => task.planner_session_id === sessionId)))
      .catch((reason: Error) => setError(reason.message));
  }, [session?.application_id, session?.status, sessionId]);

  usePolling({
    enabled: Boolean(sessionId && session?.status === "生成中"),
    interval: 1200,
    maxAttempts: 150,
    poll: async () => {
      if (!sessionId) return;
      const result = await api.planner.session(sessionId);
      setSession(result);
      setApplicationId(result.application_id);
      if (result.status === "生成中") saveSessionId(window.localStorage, activePlannerSessionKey, result.id);
      else clearDraft(window.localStorage, activePlannerSessionKey);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "备战状态读取失败"),
  });

  async function uploadResume(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try { const result = await api.planner.uploadResume(file); setProfile(result); setFileName(result.file_name ?? file.name); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "简历解析失败"); }
    finally { setUploading(false); }
  }

  async function deleteResume() {
    setLoading(true); setError("");
    try {
      await api.planner.deleteResume();
      setProfile(null);
      setFileName("");
      setConfirmingResumeDelete(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "简历删除失败");
    } finally {
      setLoading(false);
    }
  }

  async function generate() {
    if (!applicationId) return setError("请选择目标投递");
    if (!profile?.resume_text.trim()) return setError("请先上传可提取文字的 PDF 或 DOCX 简历");
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return setError("投递记录不存在");
    if (!application.position.jd_text?.trim()) return setError("目标投递缺少 JD，请先在投递台账补充");
    setLoading(true); setError("");
    try { const created = await api.planner.create({ application_id: applicationId, provider }); setSession(created); saveSessionId(window.localStorage, activePlannerSessionKey, created.id); navigate(`/planner/${created.id}`, { replace: true }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "备战分析失败"); }
    finally { setLoading(false); }
  }

  async function updateAction(task: PreparationTask, status: PreparationTask["status"]) {
    try {
      const updated = await api.planner.updateTask(task.id, status);
      setSessionTasks((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "行动状态更新失败");
    }
  }

  async function materializeActions() {
    if (!sessionId) return;
    try {
      const updated = await api.planner.materializeActions(sessionId);
      setSession(updated);
      const result = await api.planner.tasks({ application_id: updated.application_id, page_size: 100, include_deferred: true });
      setSessionTasks(result.items.filter((task) => task.planner_session_id === sessionId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "准备行动生成失败");
    }
  }

  const report = session?.draft_payload && isReport(session.draft_payload) ? session.draft_payload : null;
  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">简历、JD 与已确认面经</span>
          <h1>备战中心</h1>
          <p>上传简历后，系统结合目标岗位 JD 和该岗位面经给出差距与准备重点。</p>
        </div>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      {!sessionId && (
        <div className="planner-grid">
          <div className="panel planner-form">
            <label className="resume-upload">
              <span>简历文件</span>
              <strong>
                <UploadSimple size={19} />
                {uploading ? "正在提取文字…" : profile ? "替换 PDF 或 DOCX 简历" : "上传 PDF 或 DOCX 简历"}
              </strong>
              <input
                type="file"
                accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx"
                onChange={uploadResume}
                disabled={uploading}
              />
            </label>
            {fileName && (
              <div className="resume-file">
                <FileText size={19} />
                <div>
                  <strong>{fileName}</strong>
                  <span>{profile ? `${profile.resume_text.length.toLocaleString()} 字，已可用于分析` : "正在读取简历信息"}</span>
                </div>
                <button className="button ghost danger-button" type="button" disabled={loading} onClick={() => setConfirmingResumeDelete(true)}>
                  <Trash size={15} />删除
                </button>
              </div>
            )}
            <label>
              目标投递
              <select value={applicationId} onChange={(event) => setApplicationId(Number(event.target.value))}>
                <option value={0}>选择有 JD 的投递</option>
                {applications.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.position.jd_text?.trim()}>
                    {item.position.company.name} · {item.position.title}{item.position.jd_text?.trim() ? "" : "（缺少 JD）"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              分析模型
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                {providers.map((item) => <option key={item.name} value={item.name}>{item.label} · {item.model}</option>)}
              </select>
            </label>
            <button className="button primary" type="button" disabled={loading || uploading} onClick={generate}>
              <Sparkle size={18} />
              {loading ? "正在分析…" : "开始备战分析"}
            </button>
          </div>
          <aside className="panel planner-aside">
            <strong>分析范围</strong>
            <p>系统会读取上传简历、目标投递的 JD，以及该公司和岗位下已保存的面经。</p>
            <p>本模块只生成分析和准备清单，不自动占用时间线。</p>
            <Link to="/applications">查看投递台账</Link>
          </aside>
        </div>
      )}
      {!sessionId && (
        <section className="panel planner-history">
          <div className="section-title">
            <ClockCounterClockwise size={20} />
            <div>
              <h2>历史分析</h2>
              <span>已保存 {history.length} 次岗位备战分析</span>
            </div>
          </div>
          <div className="planner-history-list">
            {history.length ? history.map((item) => (
              <Link className="planner-history-item" to={`/planner/${item.id}`} key={item.id}>
                <div>
                  <strong>{item.application.position.company.name} · {item.application.position.title}</strong>
                  <small>{formatDateTime(item.created_at)} · {item.provider}</small>
                </div>
                <span>{item.status}</span>
              </Link>
            )) : <p className="quiet-empty">还没有历史分析。完成一次分析后会保存在这里。</p>}
          </div>
        </section>
      )}
      {session && (
        <div className="panel planner-report">
          <div className="planner-report-heading">
            <div className="section-title">
              <Sparkle size={21} />
              <div>
                <h2>岗位备战结论</h2>
                <span>{session.application.position.company.name} · {session.application.position.title} · {session.status}</span>
              </div>
            </div>
            <Link className="button ghost" to="/planner">返回并新建分析</Link>
          </div>
          {session.status === "生成中" && <div className="session-progress" role="status">正在后台分析简历、JD 和面经，完成后会自动载入。</div>}
          {session.status === "失败" && <div className="notice error" role="alert">{session.error_message ?? "备战分析失败"}</div>}
          {report && (
            <>
              <section className="planner-summary">
                <span className="eyebrow">匹配总结</span>
                <p>{report.summary ?? "暂无总结"}</p>
              </section>
              <div className="planner-report-grid">
                <section>
                  <h3>已有优势</h3>
                  {report.strengths.length ? report.strengths.map((item) => (
                    <article key={item.name}>
                      <strong>{item.name}</strong>
                      <p>{item.evidence}</p>
                    </article>
                  )) : <p className="quiet-empty">暂无明确优势。</p>}
                </section>
                <section>
                  <h3>需要补强</h3>
                  {report.gaps.length ? report.gaps.map((item) => (
                    <article key={item.name}>
                      <strong>{item.name}</strong>
                      <p>{item.evidence}</p>
                    </article>
                  )) : <p className="quiet-empty">暂无明确差距。</p>}
                </section>
              </div>
              <section className="planner-actions">
                <div className="planner-actions-heading">
                  <h3>准备行动</h3>
                  {session.status === "已完成" && sessionTasks.length < report.actions.length && (
                    <button className="button ghost compact-button" type="button" onClick={() => void materializeActions()}>生成行动</button>
                  )}
                </div>
                {report.actions.map((item, index) => {
                  const task = sessionTasks.find((candidate) => candidate.action_index === index);
                  return (
                  <article key={item.title}>
                    <span>{item.priority}</span>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.detail ?? ""}</p>
                      {item.source_ids.length > 0 && <small>引用面经：{item.source_ids.join("、")}</small>}
                      {task && <div className="planner-action-status">
                        <span className={`task-status task-status-${task.status}`}>{task.status}</span>
                        {task.status === "待处理" && <>
                          <button className="button ghost compact-button" type="button" onClick={() => void updateAction(task, "已完成")}>完成</button>
                          <button className="button ghost compact-button" type="button" onClick={() => void updateAction(task, "已跳过")}>跳过</button>
                        </>}
                        {task.status !== "待处理" && <button className="button ghost compact-button" type="button" onClick={() => void updateAction(task, "待处理")}>重新打开</button>}
                      </div>}
                    </div>
                  </article>
                  );
                })}
              </section>
            </>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirmingResumeDelete}
        title="删除当前简历？"
        description="删除后，新建备战分析前需要重新上传简历；历史分析不会被删除。"
        confirmLabel="删除简历"
        onCancel={() => setConfirmingResumeDelete(false)}
        onConfirm={deleteResume}
      />
    </section>
  );
}
