import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatDateTime } from "../format";
import { allPages } from "../requests";
import { usePolling } from "../hooks/usePolling";
import { useRequestScope } from "../hooks/useRequestScope";
import { ConfirmDialog } from "./ConfirmDialog";
import type { FollowupGoal, FollowupOperation, FollowupProposal, FollowupTaskState, TimelineNode } from "../types";

const labels: Record<FollowupOperation, string> = { add_practice: "新增练习", reschedule_task: "调整时间", skip_task: "跳过任务" };
const interviewTypes = new Set(["AI面", "一面", "二面", "三面", "HR面"]);

function timeRange(value: FollowupTaskState | null): string {
  if (!value?.scheduled_at && !value?.ends_at) return "未安排时间";
  return `${value.scheduled_at ? formatDateTime(value.scheduled_at) : "开始时间未确定"}${value.ends_at ? ` 至 ${formatDateTime(value.ends_at)}` : ""}`;
}

export function InterviewFollowup({ applicationId }: { applicationId: number }) {
  const [goals, setGoals] = useState<FollowupGoal[]>([]);
  const [nodes, setNodes] = useState<TimelineNode[]>([]);
  const [goalId, setGoalId] = useState(0);
  const [nodeId, setNodeId] = useState(0);
  const [viewId, setViewId] = useState<number | null>(null);
  const [viewed, setViewed] = useState<FollowupProposal | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const goalRequest = useRef(0);
  const capture = useRequestScope(`${applicationId}:${goalId}:${viewId}`);
  const goal = goals.find((item) => item.id === goalId);
  const node = nodes.find((item) => item.id === goal?.timeline_node_id);
  const proposal = !viewId || viewId === goal?.latest_check?.id ? goal?.latest_check : viewed;
  const candidates = nodes.filter((item) => item.status === "待处理" && interviewTypes.has(item.node_type) && !goals.some((goalItem) => goalItem.timeline_node_id === item.id));
  const active = goal?.status === "active" && node?.status === "待处理";

  useEffect(() => { setGoalId(0); setNodeId(0); setViewId(null); setSelected([]); setError(""); setBusy(false); }, [applicationId]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoaded(false);
    Promise.all([
      api.followup.goals(applicationId, controller.signal),
      allPages((page) => api.timeline.list({ application_id: applicationId, page, page_size: 100 }, controller.signal)),
    ]).then(([nextGoals, nextNodes]) => {
      if (controller.signal.aborted) return;
      setGoals(nextGoals); setNodes(nextNodes);
      setLoaded(true);
      setGoalId((current) => nextGoals.some((item) => item.id === current) ? current : nextGoals[0]?.id ?? 0);
    }).catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [applicationId, refresh]);
  useEffect(() => { setSelected([]); setConfirming(false); setBusy(false); }, [applicationId, goalId, viewId, proposal?.applicable]);
  useEffect(() => {
    if (!active || goal?.latest_check?.status === "生成中") return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      const sequence = ++goalRequest.current;
      api.followup.goal(goalId, controller.signal).then((updated) => {
        if (!controller.signal.aborted && sequence === goalRequest.current) setGoals((items) => items.map((item) => item.id === updated.id ? updated : item));
      }).catch((reason: Error) => { if (!controller.signal.aborted && sequence === goalRequest.current) setError(reason.message); });
    }, 30000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [active, applicationId, goalId, goal?.latest_check?.status]);
  usePolling({
    resourceKey: `${applicationId}:${goalId}`, enabled: goal?.latest_check?.status === "生成中", interval: 1500, maxAttempts: 300,
    poll: async (signal) => {
      const sequence = ++goalRequest.current;
      const updated = await api.followup.goal(goalId, signal);
      if (!signal.aborted && sequence === goalRequest.current) setGoals((items) => items.map((item) => item.id === updated.id ? updated : item));
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "检查状态读取失败"),
  });

  async function mutate(action: () => Promise<FollowupGoal | FollowupProposal>, kind: "goal" | "check" | "proposal") {
    const current = capture(); setBusy(true); setError("");
    try {
      const result = await action();
      if (!current()) return;
      goalRequest.current += 1;
      if (kind === "goal") {
        const updated = result as FollowupGoal;
        setGoals((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
        setGoalId(updated.id); setNodeId(0); setViewId(null); setViewed(null);
      } else {
        const updated = result as FollowupProposal;
        setGoals((items) => items.map((item) => item.id !== updated.goal_id ? item : {
          ...item,
          latest_check: kind === "check" || item.latest_check?.id === updated.id ? updated : item.latest_check,
          history: [updated, ...item.history.filter((entry) => entry.id !== updated.id)],
        }));
        if (kind === "check") { setViewId(null); setViewed(null); }
        else { setViewId(updated.id); setViewed(updated); }
        if (updated.execution_result) window.dispatchEvent(new Event("preparation-task-updated"));
      }
      setSelected([]);
    } catch (reason) {
      if (current()) { setError(reason instanceof Error ? reason.message : "操作未完成"); setSelected([]); setViewId(null); setRefresh((value) => value + 1); }
    } finally { if (current()) setBusy(false); }
  }

  async function viewProposal(id: number) {
    const current = capture(); setBusy(true); setError("");
    try { const result = await api.followup.proposal(id); if (current()) { setViewed(result); setViewId(id); setSelected([]); } }
    catch (reason) { if (current()) setError(reason instanceof Error ? reason.message : "检查记录读取失败"); }
    finally { if (current()) setBusy(false); }
  }

  return <section className="panel interview-followup" aria-label="面试持续跟进" aria-busy={loading || busy}>
    <div className="section-title"><div><h2>面试持续跟进</h2><span>选择一次待处理面试，检查准备情况并审阅调整建议。</span></div></div>
    <p className="section-help">应用运行期间每天检查一次；关闭应用后停止。建议需要你选择并确认才会执行。</p>
    {error && <div className="notice error" role="alert">{error} <button className="button ghost compact-button" type="button" onClick={() => { setError(""); setRefresh((value) => value + 1); }} disabled={loading || busy}>重新读取</button></div>}
    {loading ? <p role="status">正在读取跟进目标…</p> : !loaded ? null : <>
      <div className="followup-create"><label>目标面试<select value={nodeId} onChange={(event) => setNodeId(Number(event.target.value))} disabled={busy}><option value={0}>选择待处理面试</option>{candidates.map((item) => <option key={item.id} value={item.id}>{item.node_type} · {item.scheduled_at || item.ends_at ? formatDateTime(item.scheduled_at ?? item.ends_at) : "时间未确定"}</option>)}</select></label><button className="button ghost compact-button" type="button" disabled={!nodeId || busy} onClick={() => void mutate(() => api.followup.create(applicationId, nodeId), "goal")}>创建跟进目标</button></div>
      {!candidates.length && <p className="quiet-empty">没有可新建目标的待处理面试。</p>}
      {goals.length > 0 && <label className="followup-goal-select">已有跟进目标<select value={goalId} onChange={(event) => { setGoalId(Number(event.target.value)); setViewId(null); setViewed(null); }} disabled={busy}>{goals.map((item) => { const target = nodes.find((entry) => entry.id === item.timeline_node_id); return <option key={item.id} value={item.id}>{target?.node_type ?? "面试"} · {target?.scheduled_at || target?.ends_at ? formatDateTime(target.scheduled_at ?? target.ends_at) : "时间未确定"} · {target?.status !== "待处理" ? "已结束" : item.status === "paused" ? "已暂停" : "跟进中"}</option>; })}</select></label>}
      {goal && <>
        <div className="followup-goal-heading"><strong>{node ? `${node.node_type} · ${node.scheduled_at || node.ends_at ? formatDateTime(node.scheduled_at ?? node.ends_at) : "时间未确定"}` : "目标日程不可用"}</strong><span>{node?.status !== "待处理" ? "目标已结束" : goal.status === "paused" ? "已暂停" : "跟进中"}</span></div>
        <div className="followup-actions"><button className="button primary compact-button" type="button" disabled={!active || busy || goal.latest_check?.status === "生成中"} onClick={() => void mutate(() => api.followup.check(goal.id), "check")}>检查准备情况</button>{node?.status === "待处理" && (goal.status === "active" ? <button className="button ghost compact-button" type="button" disabled={busy} onClick={() => void mutate(() => api.followup.pause(goal.id), "goal")}>暂停跟进</button> : <button className="button ghost compact-button" type="button" disabled={busy} onClick={() => void mutate(() => api.followup.resume(goal.id), "goal")}>恢复跟进</button>)}</div>
        {goal.history.length > 0 && <label className="followup-history">检查记录<select value={viewId ?? goal.latest_check?.id ?? ""} disabled={busy} onChange={(event) => void viewProposal(Number(event.target.value))}>{goal.history.map((item) => <option key={item.id} value={item.id}>{formatDateTime(item.created_at)} · {item.status}</option>)}</select></label>}
        {proposal && <div className="followup-proposal">
          <div className="followup-goal-heading"><strong>检查结果</strong><span>{proposal.status} · {formatDateTime(proposal.created_at)}</span></div>
          {proposal.status === "生成中" && <p role="status">正在检查，可以切换页面后回来查看。</p>}
          {proposal.message && <p>{proposal.message}</p>}{proposal.error_message && <p className="notice error" role="alert">{proposal.error_message}</p>}
          {proposal.duplicate_of && <button className="button ghost compact-button" type="button" disabled={busy} onClick={() => void viewProposal(proposal.duplicate_of!)}>查看沿用的提案</button>}
          {proposal.status === "待确认" && !proposal.applicable && <p className="notice">资料或目标状态已变化，请重新检查后再确认。</p>}
          {proposal.suggestions.map((item, index) => <article className="followup-suggestion" key={index}>
            <label className="followup-suggestion-title"><input type="checkbox" aria-label={`选择建议 ${index + 1}`} checked={proposal.execution_result ? proposal.execution_result.suggestion_indexes.includes(index) : selected.includes(index)} disabled={!proposal.applicable || busy} onChange={(event) => setSelected((current) => event.target.checked ? [...current, index] : current.filter((value) => value !== index))} /><strong>{labels[item.operation]}：{item.title}</strong></label>
            <p>{item.reason}</p>
            {item.operation === "reschedule_task" && <p>原时间：{timeRange(item.before)}<br />建议时间：{timeRange(item.after)}</p>}
            {item.operation === "skip_task" && <p>确认后标记为已跳过，可在练习页恢复。</p>}
            {item.operation === "add_practice" && item.after.detail && <p>练习内容：{item.after.detail}</p>}
            <details><summary>查看依据</summary>{item.source_ids.map((id) => { const source = proposal.sources.find((entry) => entry.id === id); return source ? <div className="followup-source" key={id}><strong>{source.title}</strong><p>{source.text}</p>{/^(task|practice)-\d+$/.test(id) && <Link to={`/practice/${id.split("-")[1]}`}>打开练习</Link>}{/^timeline-\d+$/.test(id) && <Link to={`/timeline?focus=${id.split("-")[1]}`}>查看日程</Link>}</div> : null; })}</details>
          </article>)}
          {proposal.status === "待确认" && <div className="followup-actions"><button className="button primary compact-button" type="button" disabled={!proposal.applicable || busy || !selected.length} onClick={() => setConfirming(true)}>审阅并应用所选建议（{selected.length}）</button><button className="button ghost compact-button" type="button" disabled={busy} onClick={() => void mutate(() => api.followup.discard(proposal.id), "proposal")}>不采用此提案</button></div>}
          {proposal.status === "生成中" && <button className="button ghost compact-button" type="button" disabled={busy} onClick={() => void mutate(() => api.followup.discard(proposal.id), "proposal")}>取消本次检查</button>}
          {proposal.execution_result && <div className="followup-result"><strong>已执行的调整</strong>{proposal.execution_result.actions.map((item) => <p key={item.suggestion_index}>{labels[item.operation]}：<Link to={`/practice/${item.task_id}`}>查看练习</Link>{item.operation === "reschedule_task" && ` · ${timeRange(item.after)}`}{item.operation === "skip_task" && " · 已跳过，可恢复"}</p>)}</div>}
        </div>}
      </>}
    </>}
    <ConfirmDialog open={confirming} title="确认执行所选建议？" description={`将执行 ${selected.length} 项调整：${selected.map((index) => proposal?.suggestions[index] ? `${labels[proposal.suggestions[index].operation]} ${proposal.suggestions[index].title}` : "").join("；")}。执行前会重新核对任务和面试安排。`} confirmLabel="确认执行" onCancel={() => setConfirming(false)} onConfirm={() => { setConfirming(false); if (proposal) void mutate(() => api.followup.apply(proposal.id, selected), "proposal"); }} />
  </section>;
}
