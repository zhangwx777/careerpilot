import { ArrowRight, CalendarDots, ChartBar } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { formatDateTime } from "../format";
import type { Dashboard, DashboardFeedItem } from "../types";

function priorityLabel(priority: number | null): string {
  return priority === 1 ? "高" : priority === 2 ? "中" : "低";
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [removingTaskId, setRemovingTaskId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      setLoading(true);
      api.dashboard.get()
        .then((result) => { if (!cancelled) setData(result); })
        .catch((reason: Error) => { if (!cancelled) setError(reason.message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    };
    refresh();
    const onTaskUpdate = () => refresh();
    window.addEventListener("preparation-task-updated", onTaskUpdate);
    window.addEventListener("preparation-plan-updated", onTaskUpdate);
    return () => { cancelled = true; window.removeEventListener("preparation-task-updated", onTaskUpdate); window.removeEventListener("preparation-plan-updated", onTaskUpdate); };
  }, []);

  const pipeline = data?.pipeline ?? [];
  const feed = data?.feed ?? [];
  const preparationFeed = feed.filter((item) => item.kind === "preparation");
  const timelineFeed = feed.filter((item) => item.kind === "timeline");
  const totalApplications = pipeline.find((bucket) => bucket.status === "已投递")?.count ?? 0;
  const activePipeline = pipeline.filter((bucket) => bucket.count > 0);
  const maxCount = activePipeline.reduce((max, bucket) => Math.max(max, bucket.count), 0);
  const attentionCount = timelineFeed.filter((item) => item.alert_types.length > 0).length;
  const nextFeed = [...feed].sort((left, right) => {
    const leftAttention = left.kind === "timeline" && left.alert_types.length > 0;
    const rightAttention = right.kind === "timeline" && right.alert_types.length > 0;
    if (leftAttention !== rightAttention) return leftAttention ? -1 : 1;
    if (left.kind === "preparation" && right.kind === "preparation") {
      return (left.priority ?? 3) - (right.priority ?? 3);
    }
    if (left.kind === "timeline" && right.kind === "timeline") {
      return (left.scheduled_at ?? "9999").localeCompare(right.scheduled_at ?? "9999");
    }
    return left.kind === "timeline" ? -1 : 1;
  });

  function feedLink(item: DashboardFeedItem): string {
    return item.kind === "preparation" && item.task_id
      ? `/practice/${item.task_id}`
      : `/timeline?focus=${item.timeline_node_id ?? item.id}`;
  }

  async function removeTask(taskId: number) {
    setRemovingTaskId(taskId);
    setError("");
    try {
      await api.planner.removeTask(taskId);
      window.dispatchEvent(new Event("preparation-plan-updated"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "移出计划失败");
    } finally {
      setRemovingTaskId(null);
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">进度与关键节点</span>
          <h1>求职总览</h1>
          <p>把待练习行动和即将到来的求职节点放在同一条接下来时间流里。</p>
        </div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      {loading ? (
        <div className="panel loading-state" aria-label="正在读取总览数据">
          <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
        </div>
      ) : (
        <>
          <div className="dashboard-overview-grid">
            <section className="panel dashboard-panel dashboard-pipeline-card">
              <div className="section-title dashboard-card-heading">
                <ChartBar size={20} weight="duotone" aria-hidden="true" />
                <div><h2>投递分布</h2><span>查看每个阶段当前有多少条投递</span></div>
                <Link className="dashboard-card-link" to="/applications">查看投递台账 <ArrowRight size={15} aria-hidden="true" /></Link>
              </div>
              {totalApplications ? (
                <div className="pipeline-list">
                  {activePipeline.map((bucket) => <div className="pipeline-row" key={bucket.status}><span className="pipeline-label">{bucket.status}</span><span className="pipeline-track"><i style={{ width: maxCount ? `${(bucket.count / maxCount) * 100}%` : "0%" }} /></span><span className="pipeline-count">{bucket.count}</span></div>)}
                </div>
              ) : (
                <div className="empty-state dashboard-empty"><ChartBar size={36} weight="duotone" aria-hidden="true" /><strong>还没有投递记录</strong><span>先到 <Link to="/applications/new">新增投递</Link> 记录第一条。</span></div>
              )}
            </section>

            <section className="panel dashboard-panel dashboard-metrics-card">
              <div className="section-title dashboard-card-heading">
                <CalendarDots size={20} weight="duotone" aria-hidden="true" />
                <div><h2>当前关注</h2><span>优先处理最需要你动作的事项</span></div>
              </div>
              <div className="dashboard-metric-grid" aria-label="求职总览摘要">
                <div className="dashboard-stat"><span>全部投递</span><strong>{totalApplications}</strong><small>条记录</small></div>
                <div className="dashboard-stat"><span>待练习</span><strong>{preparationFeed.length}</strong><small>个行动</small></div>
                <div className="dashboard-stat dashboard-stat-attention"><span>需关注</span><strong>{attentionCount}</strong><small>个节点</small></div>
              </div>
              <Link className="dashboard-card-link dashboard-metrics-link" to="/timeline">查看完整日程 <ArrowRight size={15} aria-hidden="true" /></Link>
            </section>
          </div>

          <section className="panel dashboard-panel dashboard-next-card">
            <div className="section-title dashboard-card-heading">
              <CalendarDots size={20} weight="duotone" aria-hidden="true" />
              <div><h2>接下来</h2><span>{nextFeed.length ? `${nextFeed.length} 项待处理事项` : "当前没有待处理事项"}</span></div>
              <Link className="dashboard-card-link" to="/planner">管理学习计划 <ArrowRight size={15} aria-hidden="true" /></Link>
            </div>
            {nextFeed.length ? (
              <div className="dashboard-feed-list">
                {nextFeed.map((item) => item.kind === "preparation" ? (
                  <article className="dashboard-feed-row dashboard-feed-preparation" key={`preparation-${item.id}`}>
                    <div className="dashboard-feed-marker" aria-hidden="true">练</div>
                    <div className="dashboard-feed-main"><div className="dashboard-feed-heading"><strong>{item.title}</strong><span className="dashboard-feed-kind">{item.category}</span></div><span>{item.company_name} · {item.position_title}</span></div>
                    <div className="dashboard-feed-meta"><span className={`priority-chip priority-${item.priority ?? 3}`}>{priorityLabel(item.priority)}</span><small>待练习</small></div>
                    <div className="dashboard-feed-actions"><Link className="dashboard-feed-open" to={feedLink(item)}>进入练习 <ArrowRight size={15} aria-hidden="true" /></Link><button className="button ghost compact-button danger-button" type="button" onClick={() => void removeTask(item.task_id ?? item.id)} disabled={removingTaskId === (item.task_id ?? item.id)}>移出计划</button></div>
                  </article>
                ) : (
                  <article className="dashboard-feed-row dashboard-feed-timeline" key={`timeline-${item.id}`}>
                    <div className="dashboard-feed-marker" aria-hidden="true">事</div>
                    <div className="dashboard-feed-main"><div className="dashboard-feed-heading"><strong>{item.title}</strong><span className="dashboard-feed-kind">{item.node_type ?? "求职节点"}</span></div><span>{item.company_name} · {item.position_title}</span></div>
                    <div className="dashboard-feed-meta"><strong>{formatDateTime(item.scheduled_at)}</strong>{item.alert_types.map((alert) => <small className={`alert-chip ${alert === "逾期" || alert === "冲突" ? "alert-逾期" : "alert-临期"}`} key={alert}>{alert}</small>)}</div>
                    <Link className="dashboard-feed-open" to={feedLink(item)}>查看节点 <ArrowRight size={15} aria-hidden="true" /></Link>
                  </article>
                ))}
              </div>
            ) : <div className="empty-state dashboard-empty"><span>先在备战中心选择行动，或确认招聘通知以生成求职节点。</span><Link to="/planner">去备战中心</Link></div>}
          </section>
        </>
      )}
    </section>
  );
}
