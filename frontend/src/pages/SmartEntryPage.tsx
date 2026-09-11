import {
  ArrowRight,
  Check,
  ClockCounterClockwise,
  MagicWand,
  MagnifyingGlass,
  Trash,
} from "@phosphor-icons/react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { clearDraft, loadDraft, loadSessionId, saveDraft, saveSessionId } from "../drafts";
import { toApiDate, toLocalInput } from "../format";
import { usePolling } from "../hooks/usePolling";
import { deadlineAfterWorkdays } from "../workdays";
import {
  NODE_TYPES,
  TIME_MODES,
  type Application,
  type NodeType,
  type ParseSession,
  type TimeMode,
} from "../types";

function applicationLabel(application: Application) {
  return `${application.position.company.name} · ${application.position.title}`;
}

const noticeDraftKey = "qiuzhao-agent:notice-raw";
const activeNoticeSessionKey = "qiuzhao-agent:notice-active-session";

type NoticeSessionDraft = {
  companyName: string;
  positionTitle: string;
  applicationQuery: string;
  applicationId: number;
  nodeType: NodeType | "";
  timeMode: TimeMode;
  deadlineWorkdays: number | null;
  scheduledAt: string;
  endsAt: string;
  source: string;
};

function noticeSessionDraftKey(id: number) {
  return `qiuzhao-agent:notice-${id}`;
}

export function SmartEntryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sessionId = id ? Number(id) : null;
  const [rawText, setRawText] = useState(() => loadDraft(window.localStorage, noticeDraftKey, { rawText: "" }).rawText);
  const [session, setSession] = useState<ParseSession | null>(null);
  const [pendingSessions, setPendingSessions] = useState<ParseSession[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [applicationQuery, setApplicationQuery] = useState("");
  const [applicationId, setApplicationId] = useState(0);
  const [companyName, setCompanyName] = useState("");
  const [positionTitle, setPositionTitle] = useState("");
  const [nodeType, setNodeType] = useState<NodeType | "">("");
  const [timeMode, setTimeMode] = useState<TimeMode>("固定时间");
  const [deadlineWorkdays, setDeadlineWorkdays] = useState<number | null>(null);
  const [scheduledAt, setScheduledAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [parsing, setParsing] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [creatingApplication, setCreatingApplication] = useState(false);
  const [discardingPendingId, setDiscardingPendingId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const applySession = useCallback((value: ParseSession) => {
    setSession(value);
    if (value.status === "解析中" || value.status === "待确认") {
      saveSessionId(window.localStorage, activeNoticeSessionKey, value.id);
    } else {
      clearDraft(window.localStorage, activeNoticeSessionKey);
    }
    setRawText(value.raw_text);
    const extraction = value.extracted_payload;
    const draft = loadDraft<NoticeSessionDraft | null>(window.localStorage, noticeSessionDraftKey(value.id), null);
    setCompanyName(draft?.companyName ?? extraction?.company_name ?? "");
    setPositionTitle(draft?.positionTitle ?? extraction?.position_title ?? "");
    setNodeType(draft?.nodeType ?? extraction?.node_type ?? "");
    setTimeMode(draft?.timeMode ?? extraction?.time_mode ?? "固定时间");
    setDeadlineWorkdays(draft?.deadlineWorkdays ?? extraction?.deadline_workdays ?? null);
    setScheduledAt(draft?.scheduledAt ?? toLocalInput(extraction?.scheduled_at ?? new Date().toISOString()));
    setEndsAt(draft?.endsAt ?? toLocalInput(extraction?.ends_at ?? null));
    setSource(draft?.source ?? extraction?.source ?? "");
    setApplicationQuery(draft?.applicationQuery ??
      [extraction?.company_name, extraction?.position_title]
        .filter(Boolean)
        .join(" "),
    );
    setApplications(value.recommended_applications);
    setApplicationId(
      draft?.applicationId ?? (value.recommended_applications.length === 1
        ? value.recommended_applications[0].id
        : 0),
    );
  }, []);

  const loadPending = useCallback(() => {
    api.parseSessions
      .list({ status: "待确认", page_size: 20 })
      .then((result) => setPendingSessions(result.items))
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    loadPending();
  }, [loadPending]);

  useEffect(() => {
    let cancelled = false;
    if (!sessionId) {
      const activeSessionId = loadSessionId(window.localStorage, activeNoticeSessionKey);
      if (activeSessionId) {
        navigate(`/smart-entry/${activeSessionId}`, { replace: true });
        return;
      }
      setSession(null);
      api.parseSessions
        .list({ status: "解析中", page_size: 1 })
        .then((result) => { if (!cancelled && result.items[0]) navigate(`/smart-entry/${result.items[0].id}`, { replace: true }); })
        .catch((reason: Error) => { if (!cancelled) setError(reason.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
      return () => { cancelled = true; };
    }
    setLoading(true);
    setError("");
    api.parseSessions
      .get(sessionId)
      .then((value) => { if (!cancelled) applySession(value); })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [applySession, navigate, sessionId]);

  usePolling({
    enabled: Boolean(sessionId && session?.status === "解析中"),
    interval: 1200,
    maxAttempts: 150,
    poll: async () => {
      if (!sessionId) return;
      const value = await api.parseSessions.get(sessionId);
      applySession(value);
      if (value.status !== "解析中") loadPending();
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "解析状态读取失败"),
  });

  useEffect(() => {
    if (timeMode === "截止窗口" && scheduledAt && deadlineWorkdays) {
      setEndsAt(deadlineAfterWorkdays(scheduledAt, deadlineWorkdays));
    }
  }, [deadlineWorkdays, scheduledAt, timeMode]);

  useEffect(() => {
    if (!session) saveDraft(window.localStorage, noticeDraftKey, { rawText });
  }, [rawText, session]);

  useEffect(() => {
    if (session?.status !== "待确认") return;
    saveDraft(window.localStorage, noticeSessionDraftKey(session.id), {
      companyName, positionTitle, applicationQuery, applicationId, nodeType, timeMode,
      deadlineWorkdays, scheduledAt, endsAt, source,
    });
  }, [applicationId, applicationQuery, companyName, deadlineWorkdays, endsAt, nodeType, positionTitle, scheduledAt, session, source, timeMode]);

  async function parse(event: FormEvent) {
    event.preventDefault();
    if (!rawText.trim()) {
      setError("请先粘贴一段招聘通知");
      return;
    }
    setParsing(true);
    setError("");
    try {
      const created = await api.parseSessions.create(rawText.trim());
      clearDraft(window.localStorage, noticeDraftKey);
      applySession(created);
      loadPending();
      navigate(`/smart-entry/${created.id}`, { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "解析失败，请重新提交");
    } finally {
      setParsing(false);
    }
  }

  async function findApplications() {
    setError("");
    try {
      const result = await api.applications.list({
        q: applicationQuery.trim(),
        page_size: 50,
      });
      setApplications(result.items);
      if (!result.items.some((item) => item.id === applicationId)) {
        setApplicationId(0);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "投递查询失败");
    }
  }

  async function createApplication() {
    if (!session || !companyName.trim() || !positionTitle.trim()) {
      setError("请补全公司和岗位");
      return;
    }
    setCreatingApplication(true);
    setError("");
    try {
      const application = await api.parseSessions.createApplication(session.id, {
        company_name: companyName.trim(),
        position_title: positionTitle.trim(),
      });
      if (!nodeType) {
        await api.parseSessions.discard(session.id);
        clearDraft(window.localStorage, noticeSessionDraftKey(session.id));
        loadPending();
        navigate("/applications", { replace: true });
        return;
      }
      setApplications((current) =>
        current.some((item) => item.id === application.id)
          ? current
          : [application, ...current],
      );
      setApplicationId(application.id);
      setApplicationQuery(applicationLabel(application));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建投递失败");
    } finally {
      setCreatingApplication(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!session || !applicationId || !nodeType || !scheduledAt) {
      setError("请选择投递，并补全类型和开始时间");
      return;
    }
    setResolving(true);
    setError("");
    try {
      const confirmed = await api.parseSessions.confirm(session.id, {
        application_id: applicationId,
        node_type: nodeType,
        time_mode: timeMode,
        scheduled_at: toApiDate(scheduledAt)!,
        ends_at: toApiDate(endsAt),
        source: source.trim() || null,
      });
      clearDraft(window.localStorage, noticeSessionDraftKey(session.id));
      clearDraft(window.localStorage, activeNoticeSessionKey);
      navigate(
        `/timeline?focus=${confirmed.timeline_node_id}&date=${scheduledAt.slice(0, 10)}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setResolving(false);
    }
  }

  async function discard() {
    if (!session) return;
    setResolving(true);
    setError("");
    try {
      await api.parseSessions.discard(session.id);
      clearDraft(window.localStorage, noticeSessionDraftKey(session.id));
      clearDraft(window.localStorage, noticeDraftKey);
      clearDraft(window.localStorage, activeNoticeSessionKey);
      setSession(null);
      setRawText("");
      loadPending();
      navigate("/smart-entry", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "丢弃失败");
    } finally {
      setResolving(false);
    }
  }

  async function discardPending(id: number) {
    setDiscardingPendingId(id);
    setError("");
    try {
      await api.parseSessions.discard(id);
      setPendingSessions((current) => current.filter((item) => item.id !== id));
      if (session?.id === id) {
        clearDraft(window.localStorage, activeNoticeSessionKey);
        setSession(null);
        setRawText("");
        navigate("/smart-entry", { replace: true });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除待确认通知失败");
    } finally {
      setDiscardingPendingId(null);
    }
  }

  const extraction = session?.extracted_payload;
  const canResolve = session?.status === "待确认";
  const selectedApplication = applications.find((item) => item.id === applicationId);
  const selectedApplicationLabel = selectedApplication
    ? applicationLabel(selectedApplication)
    : `${companyName} · ${positionTitle}`;

  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">AI 提取，人工确认</span>
          <h1>通知录入</h1>
          <p>粘贴通知，核对关键信息，再把确定的安排写入时间线。</p>
        </div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      {loading ? (
        <div className="panel loading-state" aria-label="正在恢复解析会话">
          <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
        </div>
      ) : (
        <div className="smart-entry-grid">
          <form className="panel notice-input-panel" onSubmit={parse}>
            <div className="section-title">
              <MagicWand size={21} weight="duotone" aria-hidden="true" />
              <div><h2>通知原文</h2><span>邮件、短信或网页文字</span></div>
            </div>
            <textarea
              rows={16}
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              disabled={Boolean(session)}
              placeholder="例如：你好，请于 9 月 12 日 19:00 参加线上笔试，预计 90 分钟……"
              aria-label="招聘通知原文"
            />
            {!session && (
              <button className="button primary parse-button" disabled={parsing} type="submit">
                <MagicWand size={18} weight="bold" aria-hidden="true" />
                {parsing ? "正在识别通知…" : "开始识别"}
              </button>
            )}
            {session && (
              <div className="source-lock">
                <span>原文已锁定</span>
                <small>确认页会保留原始内容，便于逐项核对。</small>
              </div>
            )}
          </form>

          <form className="panel review-panel" onSubmit={confirm}>
            <div className="section-title">
              <Check size={21} weight="duotone" aria-hidden="true" />
              <div><h2>确认信息</h2><span>{session ? session.status : "识别后在这里核对"}</span></div>
            </div>

            {!session ? (
              <div className="empty-state compact-empty">
                <ArrowRight size={32} weight="duotone" aria-hidden="true" />
                <strong>粘贴一条通知</strong>
                <span>AI 只做初步提取，不会直接写入时间线。</span>
              </div>
            ) : (
              <>
                {session.status === "解析中" && <div className="session-progress" role="status">正在后台识别通知，完成后会自动显示确认信息。</div>}
                {session.status === "解析失败" && <div className="notice error" role="alert">{session.error_message ?? "通知识别失败"}</div>}
                <div className="extraction-clues">
                  <span>识别结果</span>
                  <input
                    value={companyName}
                    onChange={(event) => setCompanyName(event.target.value)}
                    placeholder="公司名称"
                    disabled={!canResolve}
                    aria-label="公司名称"
                  />
                  <input
                    value={positionTitle}
                    onChange={(event) => setPositionTitle(event.target.value)}
                    placeholder="岗位名称"
                    disabled={!canResolve}
                    aria-label="岗位名称"
                  />
                </div>
                <div className="field-block application-linker">
                  <label>这条通知属于哪次投递？</label>
                  {applicationId ? (
                    <div className="quick-application linked-application">
                      <small>已匹配已有投递：{selectedApplicationLabel}</small>
                      <button className="button ghost" type="button" onClick={() => setApplicationId(0)} disabled={!canResolve}>创建一条新的投递</button>
                    </div>
                  ) : (
                    <div className="quick-application">
                      <small>默认把它作为一次新的投递；仅在同一次投递的后续通知时关联已有记录。</small>
                      <button
                        className="button primary"
                        type="button"
                        onClick={createApplication}
                        disabled={!canResolve || creatingApplication || !companyName.trim() || !positionTitle.trim()}
                      >
                        {creatingApplication ? "正在创建…" : "创建本次投递"}
                      </button>
                    </div>
                  )}
                  <details className="existing-application-picker">
                    <summary>关联已有投递（仅用于同一次投递）</summary>
                    <div className="inline-search">
                      <input value={applicationQuery} onChange={(event) => setApplicationQuery(event.target.value)} placeholder="搜索公司、岗位或备注" aria-label="搜索投递" disabled={!canResolve} />
                      <button type="button" onClick={findApplications} disabled={!canResolve}><MagnifyingGlass size={17} aria-hidden="true" />查找</button>
                    </div>
                    <select id="application" value={applicationId || ""} onChange={(event) => setApplicationId(Number(event.target.value))} disabled={!canResolve}>
                      <option value="">选择已有投递</option>
                      {applications.map((application) => <option key={application.id} value={application.id}>{applicationLabel(application)}</option>)}
                    </select>
                  </details>
                </div>

                <div className="review-fields">
                  <label className="field-block">
                    <span>安排类型</span>
                    <select value={nodeType} onChange={(event) => setNodeType(event.target.value as NodeType)} disabled={!canResolve} required>
                      <option value="" disabled>请选择</option>
                      {NODE_TYPES.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                  <label className="field-block">
                    <span>时间方式</span>
                    <select value={timeMode} onChange={(event) => setTimeMode(event.target.value as TimeMode)} disabled={!canResolve}>
                      {TIME_MODES.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                  <label className="field-block">
                    <span>通知来源</span>
                    <input value={source} onChange={(event) => setSource(event.target.value)} disabled={!canResolve} placeholder="邮件 / 短信 / 网页" />
                  </label>
                  {timeMode === "截止窗口" && (
                    <label className="field-block">
                      <span>完成时限（工作日）</span>
                      <input
                        type="number"
                        min="1"
                        max="31"
                        value={deadlineWorkdays ?? ""}
                        onChange={(event) => setDeadlineWorkdays(event.target.value ? Number(event.target.value) : null)}
                        disabled={!canResolve}
                        required
                      />
                    </label>
                  )}
                  <label className="field-block">
                    <span>{timeMode === "截止窗口" ? "起算时间" : "开始时间"}</span>
                    <input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} disabled={!canResolve} required />
                  </label>
                  <label className="field-block">
                    <span>{timeMode === "截止窗口" ? "截止时间" : "结束时间（可选）"}</span>
                    <input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} disabled={!canResolve} min={scheduledAt || undefined} required={timeMode === "截止窗口"} />
                  </label>
                </div>

                {canResolve ? (
                  <div className="form-actions resolve-actions">
                    <button className="button ghost danger-button" type="button" onClick={discard} disabled={resolving}>
                      <Trash size={17} aria-hidden="true" />丢弃
                    </button>
                    <button className="button primary" type="submit" disabled={resolving}>
                      <Check size={17} weight="bold" aria-hidden="true" />
                      {resolving ? "正在写入…" : "确认并写入时间线"}
                    </button>
                  </div>
                ) : (
                  <div className="resolved-note">该会话已{session.status.replace("已", "")}。</div>
                )}
              </>
            )}
          </form>
        </div>
      )}

      <section className="pending-section">
        <div className="section-title">
          <ClockCounterClockwise size={20} weight="duotone" aria-hidden="true" />
          <div><h2>待确认</h2><span>刷新或重启后仍可从这里继续</span></div>
        </div>
        {pendingSessions.length === 0 ? (
          <p className="quiet-empty">当前没有等待确认的通知。</p>
        ) : (
          <div className="pending-strip">
            {pendingSessions.map((item) => (
              <article className="pending-card" key={item.id}>
                <Link to={`/smart-entry/${item.id}`}>
                  <strong>{item.extracted_payload?.company_name ?? "公司待确认"}</strong>
                  <span>{item.extracted_payload?.node_type ?? "类型待确认"} · 会话 #{item.id}</span>
                </Link>
                <button className="pending-delete" type="button" aria-label={`删除待确认通知 ${item.id}`} onClick={() => discardPending(item.id)} disabled={discardingPendingId === item.id}>
                  <Trash size={16} aria-hidden="true" />
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
