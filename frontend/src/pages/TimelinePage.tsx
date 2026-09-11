import {
  CalendarDots,
  CaretLeft,
  CaretRight,
  ListBullets,
  Warning,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import { Pagination } from "../components/Pagination";
import { formatDateTime } from "../format";
import {
  NODE_STATUSES,
  type NodeStatus,
  type Page,
  type TimelineAlert,
  type TimelineNode,
} from "../types";

const pageSize = 12;
const weekDays = ["一", "二", "三", "四", "五", "六", "日"];

function dateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function calendarTime(node: TimelineNode) {
  return node.scheduled_at
    ? new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(node.scheduled_at))
    : ""
}

function dayRange(value: string) {
  const start = new Date(`${value}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start: start.toISOString(), end: end.toISOString() };
}

function monthGrid(month: Date) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

function alertLabel(alert: TimelineAlert) {
  return <span className={`alert-chip alert-${alert}`}>{alert}</span>;
}

interface TimelineItemProps {
  node: TimelineNode;
  focused?: boolean;
  updatingId: number | null;
  onStatusChange: (node: TimelineNode, status: NodeStatus) => void;
}

function TimelineItem({ node, focused, updatingId, onStatusChange }: TimelineItemProps) {
  return (
    <article
      id={`timeline-node-${node.id}`}
      className={`timeline-item${focused ? " is-focused" : ""}`}
    >
      <div className="timeline-date-block">
        <strong>{formatDateTime(node.scheduled_at)}</strong>
        <span>{node.ends_at ? `至 ${formatDateTime(node.ends_at)}` : "未记录结束时间"}</span>
      </div>
      <div className="timeline-target">
        <div>
          <span className="node-type">{node.node_type}</span>
          {node.alert_types.map((alert) => <span key={alert}>{alertLabel(alert)}</span>)}
        </div>
        <strong>{node.title || node.application.position.company.name}</strong>
        <span>{node.application.position.title} · {node.source ?? "来源未记录"}</span>
        {node.detail && <span>{node.detail}</span>}
        {node.conflict_node_ids.length > 0 && (
          <small>与节点 #{node.conflict_node_ids.join("、#")} 时间冲突</small>
        )}
      </div>
      <label className="timeline-status-control">
        <span className="sr-only">更新节点状态</span>
        <select
          value={node.status}
          disabled={updatingId === node.id}
          onChange={(event) => onStatusChange(node, event.target.value as NodeStatus)}
        >
          {NODE_STATUSES.map((status) => <option key={status}>{status}</option>)}
        </select>
      </label>
    </article>
  );
}

export function TimelinePage() {
  const [searchParams] = useSearchParams();
  const focusId = Number(searchParams.get("focus")) || null;
  const initialDate = searchParams.get("date") ?? "";
  const [view, setView] = useState<"list" | "calendar">("list");
  const [page, setPage] = useState(1);
  const [startDate, setStartDate] = useState(initialDate);
  const [endDate, setEndDate] = useState(
    initialDate ? dayRange(initialDate).end.slice(0, 10) : "",
  );
  const [statusFilter, setStatusFilter] = useState<NodeStatus | "">("");
  const [listData, setListData] = useState<Page<TimelineNode>>({
    items: [], total: 0, page: 1, page_size: pageSize,
  });
  const [calendarMonth, setCalendarMonth] = useState(() => {
    const date = initialDate ? new Date(`${initialDate}T00:00:00`) : new Date();
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const [calendarNodes, setCalendarNodes] = useState<TimelineNode[]>([]);
  const [selectedDay, setSelectedDay] = useState(initialDate || dateKey(new Date()));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const start = startDate ? dayRange(startDate).start : undefined;
    const end = endDate ? dayRange(endDate).end : undefined;
    api.timeline
      .list({ page, page_size: pageSize, start, end, status: statusFilter || undefined })
      .then((result) => { if (!cancelled) setListData(result); })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [endDate, page, revision, startDate, statusFilter]);

  const days = useMemo(() => monthGrid(calendarMonth), [calendarMonth]);

  useEffect(() => {
    let cancelled = false;
    const rangeStart = new Date(days[0]);
    const rangeEnd = new Date(days[days.length - 1]);
    rangeEnd.setDate(rangeEnd.getDate() + 1);
    async function loadCalendar() {
      try {
        const first = await api.timeline.list({
          page: 1,
          page_size: 100,
          start: rangeStart.toISOString(),
          end: rangeEnd.toISOString(),
          status: statusFilter || undefined,
        });
        const items = [...first.items];
        for (let nextPage = 2; items.length < first.total; nextPage += 1) {
          const next = await api.timeline.list({
            page: nextPage,
            page_size: 100,
            start: rangeStart.toISOString(),
            end: rangeEnd.toISOString(),
            status: statusFilter || undefined,
          });
          items.push(...next.items);
        }
        if (!cancelled) setCalendarNodes(items);
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "月历读取失败");
      }
    }
    loadCalendar();
    return () => { cancelled = true; };
  }, [days, revision, statusFilter]);

  useEffect(() => {
    if (!focusId || loading) return;
    document.getElementById(`timeline-node-${focusId}`)?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [focusId, loading]);

  const nodesByDay = useMemo(() => {
    const grouped = new Map<string, TimelineNode[]>();
    for (const item of calendarNodes) {
      if (!item.scheduled_at) continue;
      const key = dateKey(new Date(item.scheduled_at));
      grouped.set(key, [...(grouped.get(key) ?? []), item]);
    }
    return grouped;
  }, [calendarNodes]);

  async function updateStatus(node: TimelineNode, status: NodeStatus) {
    setUpdatingId(node.id);
    setError("");
    try {
      await api.timeline.transition(node.id, status);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态更新失败");
    } finally {
      setUpdatingId(null);
    }
  }

  function moveMonth(offset: number) {
    setCalendarMonth((current) => new Date(current.getFullYear(), current.getMonth() + offset, 1));
  }

  function resetMonth() {
    const today = new Date();
    setCalendarMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    setSelectedDay(dateKey(today));
  }

  const selectedNodes = nodesByDay.get(selectedDay) ?? [];

  return (
    <section>
      <div className="page-heading timeline-heading">
        <div>
          <span className="eyebrow">安排与提醒</span>
          <h1>时间线</h1>
          <p>所有确认过的截止、笔试与面试，都在同一个时间坐标里。</p>
        </div>
        <div className="view-switch" aria-label="切换时间线视图">
          <button className={view === "list" ? "active" : ""} type="button" onClick={() => setView("list")}>
            <ListBullets size={17} aria-hidden="true" />列表
          </button>
          <button className={view === "calendar" ? "active" : ""} type="button" onClick={() => setView("calendar")}>
            <CalendarDots size={17} aria-hidden="true" />月历
          </button>
        </div>
      </div>

      <div className="filter-bar timeline-filters">
        <label className="select-control">
          <span>开始日期</span>
          <input type="date" value={startDate} onChange={(event) => { setStartDate(event.target.value); setPage(1); }} />
        </label>
        <label className="select-control">
          <span>结束日期</span>
          <input type="date" value={endDate} onChange={(event) => { setEndDate(event.target.value); setPage(1); }} />
        </label>
        <label className="select-control">
          <span>状态</span>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as NodeStatus | ""); setPage(1); }}>
            <option value="">全部状态</option>
            {NODE_STATUSES.map((status) => <option key={status}>{status}</option>)}
          </select>
        </label>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      {view === "list" ? (
        <div>
          <div className="panel timeline-list">
            {loading ? (
              <div className="loading-state" aria-label="正在读取时间线">
                <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
              </div>
            ) : listData.items.length === 0 ? (
              <div className="empty-state">
                <CalendarDots size={36} weight="duotone" aria-hidden="true" />
                <strong>这个范围内还没有安排</strong>
                <span>从智能录入确认一条通知后，它会出现在这里。</span>
              </div>
            ) : listData.items.map((item) => (
              <TimelineItem key={item.id} node={item} focused={item.id === focusId} updatingId={updatingId} onStatusChange={updateStatus} />
            ))}
          </div>
          <Pagination page={page} pageSize={pageSize} total={listData.total} onChange={setPage} />
        </div>
      ) : (
        <div className="calendar-layout">
          <section className="panel calendar-panel">
            <div className="calendar-toolbar">
              <div>
                <strong>{calendarMonth.getFullYear()} 年 {calendarMonth.getMonth() + 1} 月</strong>
                <span>点击日期查看当天详情</span>
              </div>
              <div>
                <button type="button" aria-label="上个月" onClick={() => moveMonth(-1)}><CaretLeft /></button>
                <button type="button" onClick={resetMonth}>本月</button>
                <button type="button" aria-label="下个月" onClick={() => moveMonth(1)}><CaretRight /></button>
              </div>
            </div>
            <div className="calendar-weekdays">{weekDays.map((day) => <span key={day}>周{day}</span>)}</div>
            <div className="calendar-grid">
              {days.map((day) => {
                const key = dateKey(day);
                const items = nodesByDay.get(key) ?? [];
                return (
                  <button
                    type="button"
                    key={key}
                    className={`${day.getMonth() !== calendarMonth.getMonth() ? "outside" : ""}${selectedDay === key ? " selected" : ""}`}
                    onClick={() => setSelectedDay(key)}
                  >
                    <span className="day-number">{day.getDate()}</span>
                    {items.length > 0 && <span className="calendar-events">
                      {items.slice(0, 2).map((item) => (
                        <span
                          className={`calendar-event ${item.node_type === "网申截止" || item.node_type === "测评" ? "is-deadline" : "is-interview"} ${item.alert_types.map((alert) => `is-${alert}`).join(" ")}`}
                          key={item.id}
                        >
                          <b>{item.node_type}</b>
                          <span>{item.application.position.company.name} · {calendarTime(item)}</span>
                        </span>
                      ))}
                      {items.length > 2 && <span className="calendar-more">还有 {items.length - 2} 项</span>}
                    </span>}
                  </button>
                );
              })}
            </div>
          </section>
          <aside className="panel day-detail">
            <div className="section-title">
              <Warning size={20} weight="duotone" aria-hidden="true" />
              <div><h2>{selectedDay}</h2><span>{selectedNodes.length} 项安排</span></div>
            </div>
            {selectedNodes.length === 0 ? (
              <p className="quiet-empty">当天没有安排。</p>
            ) : selectedNodes.map((item) => (
              <TimelineItem key={item.id} node={item} focused={item.id === focusId} updatingId={updatingId} onStatusChange={updateStatus} />
            ))}
          </aside>
        </div>
      )}
    </section>
  );
}
