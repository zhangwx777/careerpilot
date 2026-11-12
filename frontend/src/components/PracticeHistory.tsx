import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDateTime } from "../format";
import { useRequestScope } from "../hooks/useRequestScope";
import type { PracticeFeedbackSnapshot, PracticeHistoryItem, PracticeHistoryPage } from "../types";

function FeedbackBody({ item, includeGaps = true }: { item: Pick<PracticeHistoryItem, "question" | "user_answer" | "feedback_payload">; includeGaps?: boolean }) {
  return <div className="practice-history-feedback">
    <div><strong>原始题目</strong><p>{item.question ?? "未保留原始题目"}</p></div>
    <div><strong>用户原回答</strong><p>{item.user_answer || "未保留回答"}</p></div>
    {item.feedback_payload && <>
      <div><strong>点评中的优点</strong>{item.feedback_payload.strengths.length ? <ul>{item.feedback_payload.strengths.map((point, index) => <li key={index}>{point}</li>)}</ul> : <p>本次点评未列出优点。</p>}</div>
      {includeGaps && <div><strong>{item.feedback_payload.gaps.length ? "建议继续巩固" : "本次点评未指出明显薄弱点"}</strong>{item.feedback_payload.gaps.length > 0 && <ul>{item.feedback_payload.gaps.map((point, index) => <li key={index}>{point}</li>)}</ul>}</div>}
      <div><strong>点评改写</strong><p>{item.feedback_payload.rewrite}</p></div>
    </>}
  </div>;
}

export function PracticeHistory({ applicationId }: { applicationId: number }) {
  const [data, setData] = useState<PracticeHistoryPage | null>(null);
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState("");
  const capture = useRequestScope(`${applicationId}:${page}`);

  useEffect(() => { setPage(1); setSelected([]); setBusy(false); setError(""); }, [applicationId]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setLoading(true);
    if (!applicationId) { setLoading(false); return () => controller.abort(); }
    api.planner.practiceHistory(applicationId, page, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [applicationId, page, refresh]);
  useEffect(() => {
    const update = () => setRefresh((value) => value + 1);
    window.addEventListener("preparation-task-updated", update);
    return () => window.removeEventListener("preparation-task-updated", update);
  }, []);

  async function confirmScope() {
    if (!data || !selected.length) return;
    const isCurrent = capture();
    setBusy(true); setError("");
    try {
      await api.planner.confirmPracticeScope(applicationId, data.position_id, selected);
      if (!isCurrent()) return;
      setSelected([]); setRefresh((value) => value + 1);
    } catch (reason) {
      if (isCurrent()) { setError(reason instanceof Error ? reason.message : "确认历史计划岗位失败"); setSelected([]); setRefresh((value) => value + 1); }
    } finally { if (isCurrent()) setBusy(false); }
  }

  if (!applicationId) return null;
  const legacySessions = [...new Set(data?.items.filter((item) => !item.scope_confirmed).map((item) => item.planner_session_id) ?? [])];
  return <section className="panel practice-history" aria-label="岗位准备复盘" aria-busy={loading || busy}>
    <div className="section-title"><div><h2>岗位准备复盘</h2><span>同一岗位的练习与点评可以复用；一次练习完成不代表已经掌握。</span></div></div>
    <p className="section-help">新分析会参考同岗位最近 20 次有效点评，先生成候选行动，由你选择后加入计划。</p>
    {error && <div className="notice error" role="alert">{error} <button className="button ghost compact-button" type="button" disabled={busy || loading} onClick={() => { setError(""); setRefresh((value) => value + 1); }}>重新读取</button></div>}
    {loading ? <p role="status">正在读取练习记录…</p> : data === null ? null : !data.items.length ? <p className="quiet-empty">这个岗位还没有练习记录。</p> : <>
      {legacySessions.length > 0 && <div className="practice-history-legacy">
        <p>这些历史计划尚未确认所属岗位。确认后，其中的有效点评才会用于本岗位的新分析。</p>
        {legacySessions.map((id) => <label key={id}><input type="checkbox" disabled={busy} checked={selected.includes(id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, id] : current.filter((value) => value !== id))} />确认历史计划 #{id} 属于当前岗位 <Link to={`/planner/${id}`}>查看计划</Link></label>)}
        <button type="button" className="button ghost compact-button" disabled={busy || !selected.length} onClick={() => void confirmScope()}>确认已选历史计划的岗位</button>
      </div>}
      <div className="practice-history-list">{data.items.map((item) => <article className="practice-history-item" key={item.task_id}>
        <div className="practice-history-heading"><strong>{item.title}</strong><Link to={`/practice/${item.task_id}`}>打开练习</Link></div>
        <p className="section-help">{item.has_feedback ? "已完成练习" : "尚无有效点评"} · 任务当前：{item.status} · {item.feedback_completed_at ? formatDateTime(item.feedback_completed_at) : item.has_feedback ? "历史记录，未保留点评时间" : "尚未完成点评"}{!item.scope_confirmed && " · 岗位待确认"}</p>
        {item.has_feedback && item.feedback_payload ? <>
          <div className="practice-history-feedback"><strong>{item.feedback_payload.gaps.length ? "建议继续巩固" : "本次点评未指出明显薄弱点"}</strong><ul>{item.feedback_payload.gaps.map((point, index) => <li key={index}>{point}</li>)}</ul></div>
          <details><summary>查看本次练习与点评</summary><FeedbackBody item={item} includeGaps={false} /><p className="section-help">点评对应练习 #{item.task_id}，投递 #{item.application_id}。</p></details>
        </> : <p className="quiet-empty">完成自答点评后，这次练习才能为后续准备提供反馈。</p>}
      </article>)}</div>
      {data.total > data.page_size && <div className="practice-history-pagination"><button type="button" className="button ghost compact-button" disabled={busy || page === 1} onClick={() => { setPage(page - 1); setSelected([]); }}>上一页</button><span>第 {page} 页</span><button type="button" className="button ghost compact-button" disabled={busy || page * data.page_size >= data.total} onClick={() => { setPage(page + 1); setSelected([]); }}>下一页</button></div>}
    </>}
  </section>;
}

export function PracticeFeedbackSources({ items }: { items: PracticeFeedbackSnapshot[] }) {
  return <section className="practice-feedback-sources" aria-label="本次使用的练习反馈">
    <details><summary>查看 {items.length} 次点评来源（生成时快照）</summary>
      {items.length ? items.map((item) => <details id={`feedback-source-${item.source_id}`} key={item.source_id}>
        <summary>练习 #{item.task_id} · {item.title}</summary>
        <p className="section-help">计划 #{item.planner_session_id} · 投递 #{item.application_id} · {item.feedback_completed_at ? formatDateTime(item.feedback_completed_at) : "历史记录，未保留点评时间"}</p>
        <FeedbackBody item={item} />
      </details>) : <p className="quiet-empty">本次分析没有使用历史点评。</p>}
    </details>
  </section>;
}

export function PracticeEvidenceLink({ source }: { source: PracticeFeedbackSnapshot }) {
  return <a href={`#feedback-source-${source.source_id}`} onClick={() => {
    let element: HTMLElement | null = document.getElementById(`feedback-source-${source.source_id}`);
    while (element) { if (element instanceof HTMLDetailsElement) element.open = true; element = element.parentElement; }
  }}>练习 #{source.task_id}：{source.title}</a>;
}
