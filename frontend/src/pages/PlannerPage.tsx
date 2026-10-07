import { ClockCounterClockwise, FileText, Sparkle, Trash, UploadSimple } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { allPages } from "../requests";
import { useRequestScope } from "../hooks/useRequestScope";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { loadDraft, loadSessionId, saveDraft, saveSessionId, clearDraft } from "../drafts";
import { formatDateTime } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Application, PlannerReport, PlannerSession, PreparationCategory, PreparationTask, ResumeProfile } from "../types";

const plannerDraftKey = "qiuzhao-agent:planner-draft";
const activePlannerSessionKey = "qiuzhao-agent:planner-active-session";
type PlannerDraft = { applicationId: number; fileName: string };

const priorityLabels = ["", "高", "中", "低"];
function priorityLabel(priority: number) { return priorityLabels[Math.min(Math.max(priority, 1), 3)] ?? "中"; }
const categories: PreparationCategory[] = ["八股", "简历内容"];
const resumeCategoryHints = ["简历", "项目", "经历", "负责", "贡献", "复盘", "落地", "挑战", "团队", "离职", "自我介绍"];

function normalizeCategory(title: string, detail: string | null | undefined, category?: string): PreparationCategory {
  const text = `${title} ${detail ?? ""}`;
  return category === "简历内容" || resumeCategoryHints.some((hint) => text.includes(hint)) ? "简历内容" : "八股";
}

function isReport(value: PlannerSession["draft_payload"]): value is PlannerReport {
  return Boolean(value && "actions" in value);
}

export function PlannerPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sessionId = id ? Number(id) : null;
  const draft = loadDraft<PlannerDraft>(window.localStorage, plannerDraftKey, { applicationId: 0, fileName: "" });
  const [applications, setApplications] = useState<Application[]>([]);
  const [applicationId, setApplicationId] = useState(draft.applicationId);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [fileName, setFileName] = useState(draft.fileName);
  const [session, setSession] = useState<PlannerSession | null>(null);
  const [history, setHistory] = useState<PlannerSession[]>([]);
  const [sessionTasks, setSessionTasks] = useState<PreparationTask[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [confirmingResumeDelete, setConfirmingResumeDelete] = useState(false);
  const [deletingSession, setDeletingSession] = useState<PlannerSession | null>(null);
  const [error, setError] = useState("");
  const captureRequest = useRequestScope(`${sessionId}:${applicationId}`);
  useEffect(() => { setLoading(false); setUploading(false); setError(""); }, [sessionId, applicationId]);
  const [selectedActionIndexes, setSelectedActionIndexes] = useState<number[]>([]);

  useEffect(() => {
    let cancelled = false;
    allPages((page) => api.applications.list({ page, page_size: 100 })).then((result) => { if (!cancelled) setApplications(result); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    api.planner.resume().then((result) => { if (!cancelled) { setProfile(result); setFileName(result.file_name ?? ""); } }).catch(() => { if (!cancelled) { setProfile(null); setFileName(""); } });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => { saveDraft(window.localStorage, plannerDraftKey, { applicationId, fileName }); }, [applicationId, fileName]);
  useEffect(() => {
    let cancelled = false;
    if (!sessionId) {
      setSession(null);
      const active = loadSessionId(window.localStorage, activePlannerSessionKey);
      api.planner.sessions().then((items) => {
        if (cancelled) return;
        setHistory(items);
        const isResumable = (item: PlannerSession) => item.status === "生成中" || item.status === "待确认";
        const resumable = items.find((item) => item.id === active && isResumable(item)) ?? items.find(isResumable);
        if (resumable) {
          saveSessionId(window.localStorage, activePlannerSessionKey, resumable.id);
          navigate(`/planner/${resumable.id}`, { replace: true });
        } else {
          clearDraft(window.localStorage, activePlannerSessionKey);
        }
      }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
      return () => { cancelled = true; };
    }
    setSession(null);
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
    let cancelled = false;
    const refreshTasks = () => allPages((page) => api.planner.tasks({ planner_session_id: sessionId, page, page_size: 100, include_deferred: true }))
      .then((result) => {
        if (cancelled) return;
        const tasks = result;
        setSessionTasks(tasks);
        setSelectedActionIndexes([]);
      })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    refreshTasks();
    window.addEventListener("preparation-task-updated", refreshTasks);
    window.addEventListener("preparation-plan-updated", refreshTasks);
    return () => { cancelled = true; window.removeEventListener("preparation-task-updated", refreshTasks); window.removeEventListener("preparation-plan-updated", refreshTasks); };
  }, [session?.application_id, session?.status, sessionId]);

  useEffect(() => {
    const target = window.location.hash ? document.getElementById(window.location.hash.slice(1)) : null;
    if (target) window.requestAnimationFrame(() => target.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [sessionTasks.length]);

  usePolling({
    resourceKey: sessionId,
    enabled: Boolean(sessionId && session?.status === "生成中"),
    interval: 1200,
    maxAttempts: 150,
    poll: async (signal) => {
      if (!sessionId) return;
      const result = await api.planner.session(sessionId, signal);
      if (signal.aborted) return;
      setSession(result);
      setApplicationId(result.application_id);
      if (result.status === "生成中") saveSessionId(window.localStorage, activePlannerSessionKey, result.id);
      else clearDraft(window.localStorage, activePlannerSessionKey);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "备战状态读取失败"),
  });

  async function uploadResume(event: React.ChangeEvent<HTMLInputElement>) { const isCurrent = captureRequest();
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try { const result = await api.planner.uploadResume(file); if (!isCurrent()) return; setProfile(result); setFileName(result.file_name ?? file.name); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "简历解析失败"); }
    finally { if (isCurrent()) setUploading(false); }
  }

  async function deleteResume() { const isCurrent = captureRequest();
    setLoading(true); setError("");
    try {
      await api.planner.deleteResume(); if (!isCurrent()) return;
      setProfile(null);
      setFileName("");
      setConfirmingResumeDelete(false);
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "简历删除失败");
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }

  async function generate() { const isCurrent = captureRequest();
    if (!applicationId) return setError("请选择目标投递");
    if (!profile?.resume_text.trim()) return setError("请先上传可提取文字的 PDF 或 DOCX 简历");
    const application = applications.find((item) => item.id === applicationId);
    if (!application) return setError("投递记录不存在");
    if (!application.position.jd_text?.trim()) return setError("目标投递缺少 JD，请先在投递台账补充");
    setLoading(true); setError("");
    try { const created = await api.planner.create({ application_id: applicationId }); if (!isCurrent()) return; setSession(created); saveSessionId(window.localStorage, activePlannerSessionKey, created.id); navigate(`/planner/${created.id}`, { replace: true }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "备战分析失败"); }
    finally { if (isCurrent()) setLoading(false); }
  }

  async function retrySession() { const isCurrent = captureRequest();
    if (!sessionId) return;
    setLoading(true); setError("");
    try {
      const next = await api.planner.retry(sessionId); if (!isCurrent()) return;
      setSession(next);
      saveSessionId(window.localStorage, activePlannerSessionKey, next.id);
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "重试失败");
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }

  async function updateAction(task: PreparationTask, input: { status?: PreparationTask["status"]; category?: PreparationCategory }) { const isCurrent = captureRequest();
    try {
      const updated = await api.planner.updateTask(task.id, input); if (!isCurrent()) return;
      setSessionTasks((current) => current.map((item) => item.id === updated.id ? updated : item));
      window.dispatchEvent(new Event("preparation-task-updated"));
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "行动状态更新失败");
    }
  }

  async function materializeActions() { const isCurrent = captureRequest();
    if (!sessionId) return;
    if (!selectedActionIndexes.length) return setError("请至少选择一项准备行动");
    try {
      const updated = await api.planner.materializeActions(sessionId, selectedActionIndexes); if (!isCurrent()) return;
      setSession(updated);
      const result = await allPages((page) => api.planner.tasks({ planner_session_id: sessionId, page, page_size: 100, include_deferred: true }));
      if (!isCurrent()) return;
      setSessionTasks(result);
      setSelectedActionIndexes([]);
      window.dispatchEvent(new Event("preparation-plan-updated"));
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "准备行动生成失败");
    }
  }

  async function removeAction(task: PreparationTask) { const isCurrent = captureRequest();
    try {
      await api.planner.removeTask(task.id); if (!isCurrent()) return;
      setSessionTasks((current) => current.filter((item) => item.id !== task.id));
      window.dispatchEvent(new Event("preparation-plan-updated"));
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "移出学习计划失败");
    }
  }

  async function deleteSession() { const isCurrent = captureRequest();
    if (!deletingSession) return;
    const target = deletingSession;
    setError("");
    try {
      await api.planner.remove(target.id); if (!isCurrent()) return;
      setHistory((current) => current.filter((item) => item.id !== target.id));
      if (sessionId === target.id) {
        clearDraft(window.localStorage, activePlannerSessionKey);
        navigate("/planner", { replace: true });
      }
      setDeletingSession(null);
    } catch (reason) { if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : "历史分析删除失败");
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
            <p className="field-help">已按当前设置自动选择分析模型。</p>
            <button className="button primary" type="button" disabled={loading || uploading} onClick={generate}>
              <Sparkle size={18} />
              {loading ? "正在分析…" : "开始备战分析"}
            </button>
          </div>
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
              <div className="planner-history-item" key={item.id}>
                <Link to={`/planner/${item.id}`}>
                <div>
                  <strong>{item.application.position.company.name} · {item.application.position.title}</strong>
                  <small>{formatDateTime(item.created_at)} · {item.provider}</small>
                </div>
                <span>{item.status}</span>
                </Link>
                <button className="button ghost compact-button danger-button" type="button" onClick={() => setDeletingSession(item)} aria-label={`删除 ${item.application.position.company.name} ${item.application.position.title} 的历史分析`}><Trash size={15} />删除</button>
              </div>
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
          {session.status === "失败" && <div className="notice error" role="alert"><span>{session.error_message ?? "备战分析失败"}</span><button className="button ghost compact-button" type="button" disabled={loading} onClick={() => void retrySession()}>重试</button></div>}
          {report && (
            <>
              <section className="planner-summary">
                <span className="eyebrow">岗位结论</span>
                <p>{report.summary ?? "暂无总结"}</p>
                <div className="planner-summary-stats">
                  <span><strong>{report.strengths.length}</strong> 项已有优势</span>
                  <span><strong>{report.gaps.length}</strong> 项待补强</span>
                  <span><strong>{sessionTasks.length}</strong> 项已加入计划</span>
                </div>
              </section>
              <div className="planner-report-grid">
                <section className="planner-insight-group planner-insight-strengths">
                  <div className="planner-insight-heading"><div><span>与岗位要求相符</span><h3>已有优势</h3></div><strong>{report.strengths.length} 项</strong></div>
                  {report.strengths.length ? report.strengths.map((item) => (
                    <details className="planner-insight-item" key={item.name}>
                      <summary><span className="planner-insight-summary-copy"><strong>{item.name}</strong><span className="planner-insight-preview">{item.evidence}</span></span><span className="planner-insight-expand"><span>展开依据</span><span>收起依据</span></span></summary>
                      <p>{item.evidence}</p>
                    </details>
                  )) : <p className="quiet-empty">暂无明确优势。</p>}
                </section>
                <section className="planner-insight-group planner-insight-gaps">
                  <div className="planner-insight-heading"><div><span>准备行动的切入点</span><h3>需要补强</h3></div><strong>{report.gaps.length} 项</strong></div>
                  {report.gaps.length ? report.gaps.map((item) => (
                    <details className="planner-insight-item" key={item.name}>
                      <summary><span className="planner-insight-summary-copy"><strong>{item.name}</strong><span className="planner-insight-preview">{item.evidence}</span></span><span className="planner-insight-expand"><span>展开依据</span><span>收起依据</span></span></summary>
                      <p>{item.evidence}</p>
                    </details>
                  )) : <p className="quiet-empty">暂无明确差距。</p>}
                </section>
              </div>
              <section className="planner-actions">
                <div className="planner-actions-heading">
                  <div><h3>候选准备行动</h3><p className="section-help">先选你这轮真正要准备的内容，再加入学习计划。</p></div>
                  {session.status === "已完成" && <button className="button primary compact-button" type="button" disabled={!selectedActionIndexes.length} onClick={() => void materializeActions()}>加入学习计划（{selectedActionIndexes.length}）</button>}
                </div>
                {report.actions.map((item, index) => {
                  const task = sessionTasks.find((candidate) => candidate.action_index === index);
                  const actionCategory = normalizeCategory(item.title, item.detail, item.category);
                  const selected = selectedActionIndexes.includes(index);
                  return (
                  <article id={task ? `planner-task-${task.id}` : undefined} className={`planner-action-card${selected || task ? " is-selected" : ""}`} key={`${item.title}-${index}`}>
                    <div className="planner-action-select">
                      {task ? <span className="planner-in-plan">已加入</span> : <label className="planner-action-check" title="选择此行动">
                        <input aria-label="选择此行动" type="checkbox" checked={selected} onChange={() => setSelectedActionIndexes((current) => current.includes(index) ? current.filter((value) => value !== index) : [...current, index])} />
                      </label>}
                    </div>
                    <div className="planner-action-body">
                      <div className="planner-action-title-row">
                        <div className="planner-action-title"><strong>{item.title}</strong></div>
                        <div className="planner-action-side-meta">
                          {task ? <label className="planner-category-control"><span>分类</span><select value={normalizeCategory(task.title, task.detail, task.category)} onChange={(event) => void updateAction(task, { category: event.target.value as PreparationCategory })}>{categories.map((category) => <option key={category} value={category}>{category}</option>)}</select></label> : <span className="planner-category">{actionCategory}</span>}
                          <span className={`planner-priority planner-priority-${Math.min(Math.max(item.priority, 1), 3)}`}>{priorityLabel(item.priority)}</span>
                        </div>
                      </div>
                      <p className="planner-action-detail">{item.detail ?? ""}</p>
                      <div className="planner-action-meta">{item.gap && <span>关联差距：{item.gap}</span>}</div>
                      {item.evidence?.length ? <details className="planner-evidence"><summary>查看依据</summary><ul>{item.evidence.map((evidence, evidenceIndex) => <li key={`${evidence.kind}-${evidenceIndex}`}>{evidence.kind}：{evidence.reference}</li>)}</ul></details> : null}
                      {task && <div className="planner-action-controls">
                        <span className={`task-status task-status-${task.status}`}>{task.status}</span>
                        <Link className="button primary compact-button" to={`/practice/${task.id}`}>进入练习</Link>
                        {task.status === "待处理" && <button className="button ghost compact-button danger-button" type="button" onClick={() => void removeAction(task)}>移出计划</button>}
                        {task.status === "待处理" && <button className="button ghost compact-button" type="button" onClick={() => void updateAction(task, { status: "已跳过" })}>跳过</button>}
                        {task.status === "已跳过" && <button className="button ghost compact-button" type="button" onClick={() => void updateAction(task, { status: "待处理" })}>恢复练习</button>}
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
      <ConfirmDialog
        open={Boolean(deletingSession)}
        title="删除历史分析？"
        description={deletingSession ? `将删除 ${deletingSession.application.position.company.name} · ${deletingSession.application.position.title} 的分析和准备行动，原岗位与简历资料不会删除。` : ""}
        confirmLabel="删除分析"
        onCancel={() => setDeletingSession(null)}
        onConfirm={deleteSession}
      />
    </section>
  );
}
