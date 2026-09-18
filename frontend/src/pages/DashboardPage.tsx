import { useEffect, useState } from "react";
import { ArrowRight, ChartBar, CheckCircle, Clock, Warning } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { formatDateTime } from "../format";
import type { Dashboard, DashboardAction, TimelineNode } from "../types";

type AttentionGroupKey = "overdue" | "today" | "week" | "later";

const attentionGroupMeta: { key: AttentionGroupKey; label: string; hint: string }[] = [
  { key: "overdue", label: "已逾期", hint: "需要尽快补处理" },
  { key: "today", label: "今天", hint: "今天安排的节点" },
  { key: "week", label: "本周", hint: "接下来几天的安排" },
  { key: "later", label: "更晚", hint: "提前留意的节点" },
];

function shanghaiDateKey(value: string | Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(typeof value === "string" ? new Date(value) : value);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function shiftDate(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function attentionGroup(node: TimelineNode, today: string): AttentionGroupKey {
  if (node.alert_types.includes("逾期")) return "overdue";
  const nodeDate = node.scheduled_at ? shanghaiDateKey(node.scheduled_at) : "";
  if (nodeDate === today) return "today";
  const todayDate = new Date(`${today}T00:00:00Z`);
  const day = todayDate.getUTCDay();
  const monday = shiftDate(today, day === 0 ? -6 : 1 - day);
  return nodeDate >= monday && nodeDate <= shiftDate(monday, 6) ? "week" : "later";
}

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatingTaskId, setUpdatingTaskId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.dashboard
      .get()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pipeline = data?.pipeline ?? [];
  const attention = data?.attention ?? [];
  const totalApplications = pipeline.find((bucket) => bucket.status === "已投递")?.count ?? 0;
  const activePipeline = pipeline.filter((bucket) => bucket.count > 0);
  const maxCount = activePipeline.reduce((max, bucket) => Math.max(max, bucket.count), 0);
  const currentStages = activePipeline.filter((bucket) => bucket.status !== "已投递");
  const leadingStage = currentStages.reduce(
    (leading, bucket) => (bucket.count > (leading?.count ?? 0) ? bucket : leading),
    currentStages[0],
  );
  const today = shanghaiDateKey(new Date());
  const attentionGroups = attentionGroupMeta.map((group) => ({
    ...group,
    items: attention.filter((node) => attentionGroup(node, today) === group.key),
  }));

  async function updateAction(task: DashboardAction, status: DashboardAction["status"], deferredUntil?: string | null) {
    setUpdatingTaskId(task.task_id);
    setError("");
    try {
      await api.planner.updateTask(task.task_id, status, deferredUntil);
      setData((current) => {
        if (!current) return current;
        const remaining = current.today_actions.items.filter((item) => item.task_id !== task.task_id);
        const nextTask = status === "待处理" && !deferredUntil
          ? { ...task, status, deferred_until: null }
          : null;
        return {
          ...current,
          today_actions: {
            ...current.today_actions,
            items: nextTask ? [...remaining, nextTask].sort((a, b) => a.priority - b.priority) : remaining,
            total: Math.max(0, current.today_actions.total - (nextTask ? 0 : 1)),
            pending_count: Math.max(0, current.today_actions.pending_count - (nextTask ? 0 : 1)),
          },
        };
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "行动状态更新失败");
    } finally {
      setUpdatingTaskId(null);
    }
  }

  function tomorrowAtNine(): string {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(9, 0, 0, 0);
    return date.toISOString();
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">进度与关键节点</span>
          <h1>求职总览</h1>
          <p>先看需要马上处理的节点，再看各阶段的投递分布。</p>
        </div>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      {loading ? (
        <div className="panel loading-state" aria-label="正在读取总览数据">
          <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
        </div>
      ) : (
        <>
          <section className="panel dashboard-panel dashboard-actions-panel">
            <div className="section-title">
              <CheckCircle size={20} weight="duotone" aria-hidden="true" />
              <div>
                <h2>今天先做</h2>
                <span>{data?.today_actions.total ? `${data.today_actions.total} 个准备行动待处理` : "当前没有待完成的准备行动"}</span>
              </div>
            </div>
            {data?.today_actions.items.length ? (
              <div className="dashboard-action-items">
                {data.today_actions.items.map((task) => (
                  <article className="dashboard-action-row" key={task.task_id}>
                    <div className="dashboard-action-main">
                      <div className="dashboard-action-heading">
                        <span className={`priority-chip priority-${task.priority}`}>P{task.priority}</span>
                        <strong>{task.title}</strong>
                      </div>
                      <span>{task.company_name} · {task.position_title}</span>
                      {task.detail && <p>{task.detail}</p>}
                      <small><Clock size={14} /> 预计 {task.estimated_minutes} 分钟</small>
                    </div>
                    <div className="dashboard-action-actions">
                      <button className="button primary compact-button" type="button" disabled={updatingTaskId === task.task_id} onClick={() => void updateAction(task, "已完成")}>完成</button>
                      <button className="button ghost compact-button" type="button" disabled={updatingTaskId === task.task_id} onClick={() => void updateAction(task, "已跳过")}>跳过</button>
                      <button className="button ghost compact-button" type="button" disabled={updatingTaskId === task.task_id} onClick={() => void updateAction(task, "待处理", tomorrowAtNine())}>明天再做</button>
                      <label className="defer-picker">
                        <span className="sr-only">选择延期时间</span>
                        <input
                          type="datetime-local"
                          aria-label={`选择 ${task.title} 的延期时间`}
                          disabled={updatingTaskId === task.task_id}
                          onChange={(event) => {
                            if (event.target.value) void updateAction(task, "待处理", new Date(event.target.value).toISOString());
                          }}
                        />
                      </label>
                      <Link className="dashboard-action-link" to={`/applications/${task.application_id}/edit`}>岗位</Link>
                      <Link className="dashboard-action-link" to={`/planner/${task.planner_session_id ?? ""}`} aria-label={`查看 ${task.title}`}>
                        查看 <ArrowRight size={15} />
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <CheckCircle size={36} weight="duotone" aria-hidden="true" />
                <strong>当前没有待完成的准备行动</strong>
                <span>上传简历并生成一次备战分析后，准备行动会出现在这里。</span>
                <Link to="/planner">去备战中心</Link>
              </div>
            )}
            {(data?.today_actions.total ?? 0) > (data?.today_actions.items.length ?? 0) && (
              <Link className="dashboard-more-link" to="/planner">查看全部行动 <ArrowRight size={15} /></Link>
            )}
          </section>

          <div className="dashboard-stats" aria-label="求职总览摘要">
            <div className="dashboard-stat">
              <span>全部投递</span>
              <strong>{totalApplications}</strong>
              <small>条记录</small>
            </div>
            <div className="dashboard-stat">
              <span>需要处理</span>
              <strong>{attention.length}</strong>
              <small>个关注节点</small>
            </div>
            <div className="dashboard-stat">
              <span>主要阶段</span>
              <strong>{leadingStage?.status ?? "—"}</strong>
              <small>{leadingStage ? `${leadingStage.count} 条投递` : "等待第一条投递"}</small>
            </div>
          </div>

          <div className="dashboard-grid">
          <section className="panel dashboard-panel">
            <div className="section-title">
              <Warning size={20} weight="duotone" aria-hidden="true" />
              <div>
                <h2>需要关注</h2>
                <span>{attention.length ? `${attention.length} 个待处理节点需要留意` : "没有冲突、临期或逾期的节点"}</span>
              </div>
            </div>
            {attention.length ? (
              <div className="dashboard-attention">
                {attentionGroups.filter((group) => group.items.length > 0).map((group) => (
                  <section className="dashboard-attention-group" key={group.key}>
                    <div className="dashboard-attention-group-heading">
                      <strong>{group.label}</strong>
                      <span>{group.hint}</span>
                      <b>{group.items.length}</b>
                    </div>
                    <div className="dashboard-attention-items">
                      {group.items.map((node) => (
                        <Link className="dashboard-attention-row" key={node.id} to="/timeline">
                          <div className="dashboard-attention-main">
                            <strong>
                              {node.application.position.company.name} · {node.application.position.title}
                            </strong>
                            <span>{node.title || node.node_type} · {formatDateTime(node.scheduled_at)}</span>
                          </div>
                          <div className="dashboard-attention-tags">
                            <span className="node-type">{node.node_type}</span>
                            {node.alert_types.map((alert) => (
                              <span className={`alert-chip alert-${alert}`} key={alert}>{alert}</span>
                            ))}
                          </div>
                        </Link>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <CheckCircle size={36} weight="duotone" aria-hidden="true" />
                <strong>暂时没有紧急节点</strong>
                <span>有笔试、面试撞车或临近截止时，会出现在这里。</span>
              </div>
            )}
          </section>

          <section className="panel dashboard-panel">
            <div className="section-title">
              <ChartBar size={20} weight="duotone" aria-hidden="true" />
              <div>
                <h2>投递分布</h2>
                <span>已投递为累计总数，其余为当前所在阶段</span>
              </div>
            </div>
            {totalApplications ? (
              <div className="pipeline-list">
                {activePipeline.map((bucket) => (
                  <div className="pipeline-row" key={bucket.status}>
                    <span className="pipeline-label">{bucket.status}</span>
                    <span className="pipeline-track">
                      <i style={{ width: maxCount ? `${(bucket.count / maxCount) * 100}%` : "0%" }} />
                    </span>
                    <span className="pipeline-count">{bucket.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <ChartBar size={36} weight="duotone" aria-hidden="true" />
                <strong>还没有投递记录</strong>
                <span>
                  先到 <Link to="/applications/new">新增投递</Link> 记录第一条。
                </span>
              </div>
            )}
          </section>
          </div>
        </>
      )}
    </section>
  );
}
