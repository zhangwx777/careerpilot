import { useEffect, useState } from "react";
import { ChartBar, CheckCircle, Warning } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { formatDateTime } from "../format";
import type { Dashboard, TimelineNode } from "../types";

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
