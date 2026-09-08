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
import { toApiDate, toLocalInput } from "../format";
import {
  NODE_TYPES,
  type Application,
  type NodeType,
  type ParseSession,
} from "../types";

function applicationLabel(application: Application) {
  return `${application.position.company.name} · ${application.position.title}`;
}

export function SmartEntryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sessionId = id ? Number(id) : null;
  const [rawText, setRawText] = useState("");
  const [session, setSession] = useState<ParseSession | null>(null);
  const [pendingSessions, setPendingSessions] = useState<ParseSession[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [applicationQuery, setApplicationQuery] = useState("");
  const [applicationId, setApplicationId] = useState(0);
  const [nodeType, setNodeType] = useState<NodeType | "">("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [parsing, setParsing] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState("");

  const applySession = useCallback((value: ParseSession) => {
    setSession(value);
    setRawText(value.raw_text);
    const extraction = value.extracted_payload;
    setNodeType(extraction?.node_type ?? "");
    setScheduledAt(toLocalInput(extraction?.scheduled_at ?? null));
    setEndsAt(toLocalInput(extraction?.ends_at ?? null));
    setSource(extraction?.source ?? "");
    setApplicationQuery(
      [extraction?.company_name, extraction?.position_title]
        .filter(Boolean)
        .join(" "),
    );
    setApplications(value.recommended_applications);
    setApplicationId(
      value.recommended_applications.length === 1
        ? value.recommended_applications[0].id
        : 0,
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
    if (!sessionId) {
      setLoading(false);
      setSession(null);
      return;
    }
    setLoading(true);
    setError("");
    api.parseSessions
      .get(sessionId)
      .then(applySession)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [applySession, sessionId]);

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
        scheduled_at: toApiDate(scheduledAt)!,
        ends_at: toApiDate(endsAt),
        source: source.trim() || null,
      });
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

  const extraction = session?.extracted_payload;
  const canResolve = session?.status === "待确认";

  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">AI 辅助 · 人工决定</span>
          <h1>智能录入</h1>
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
              <div><h2>人工确认单</h2><span>{session ? `会话 #${session.id} · ${session.status}` : "识别后在这里核对"}</span></div>
            </div>

            {!session ? (
              <div className="empty-state compact-empty">
                <ArrowRight size={32} weight="duotone" aria-hidden="true" />
                <strong>等待一段通知</strong>
                <span>AI 只做初步提取，不会直接写入时间线。</span>
              </div>
            ) : (
              <>
                <div className="extraction-clues">
                  <span>识别线索</span>
                  <strong>{extraction?.company_name ?? "公司未识别"}</strong>
                  <em>{extraction?.position_title ?? "岗位未识别"}</em>
                </div>
                <div className="field-block">
                  <div className="field-heading">
                    <label htmlFor="application">关联投递</label>
                    <Link to="/applications">管理投递</Link>
                  </div>
                  <div className="inline-search">
                    <input
                      value={applicationQuery}
                      onChange={(event) => setApplicationQuery(event.target.value)}
                      placeholder="搜索公司、岗位或备注"
                      aria-label="搜索投递"
                      disabled={!canResolve}
                    />
                    <button type="button" onClick={findApplications} disabled={!canResolve}>
                      <MagnifyingGlass size={17} aria-hidden="true" />查找
                    </button>
                  </div>
                  <select
                    id="application"
                    value={applicationId || ""}
                    onChange={(event) => setApplicationId(Number(event.target.value))}
                    disabled={!canResolve}
                    required
                  >
                    <option value="" disabled>选择现有投递</option>
                    {applications.map((application) => (
                      <option key={application.id} value={application.id}>
                        {applicationLabel(application)}
                      </option>
                    ))}
                  </select>
                  {applications.length === 0 && (
                    <small>没有匹配投递。请先去投递台账新增，再回来继续确认。</small>
                  )}
                </div>

                <div className="review-fields">
                  <label className="field-block">
                    <span>节点类型</span>
                    <select value={nodeType} onChange={(event) => setNodeType(event.target.value as NodeType)} disabled={!canResolve} required>
                      <option value="" disabled>请选择</option>
                      {NODE_TYPES.map((value) => <option key={value}>{value}</option>)}
                    </select>
                  </label>
                  <label className="field-block">
                    <span>来源</span>
                    <input value={source} onChange={(event) => setSource(event.target.value)} disabled={!canResolve} placeholder="邮件 / 短信 / 网页" />
                  </label>
                  <label className="field-block">
                    <span>开始时间</span>
                    <input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} disabled={!canResolve} required />
                  </label>
                  <label className="field-block">
                    <span>结束时间（可选）</span>
                    <input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} disabled={!canResolve} min={scheduledAt || undefined} />
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
              <Link key={item.id} to={`/smart-entry/${item.id}`}>
                <strong>{item.extracted_payload?.company_name ?? "公司待确认"}</strong>
                <span>{item.extracted_payload?.node_type ?? "类型待确认"} · 会话 #{item.id}</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
