import { Bell, Play, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { formatDateTime } from "../format";
import type { DailyBriefing } from "../types";

export function BriefingPage() {
  const [items, setItems] = useState<DailyBriefing[]>([]);
  const [selected, setSelected] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.briefings.list({ page_size: 30 }).then((result) => { setItems(result.items); setSelected(result.items[0] ?? null); }).catch((reason: Error) => setError(reason.message)); }, []);
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
  const hasToday = items.some((item) => item.briefing_date === today);
  async function run() { setLoading(true); setError(""); try { const result = await api.briefings.run(); setSelected(result); setItems((current) => [result, ...current.filter((item) => item.id !== result.id)]); } catch (reason) { setError(reason instanceof Error ? reason.message : "简报生成失败"); } finally { setLoading(false); } }
  return (
    <section>
      <div className="page-heading">
        <div>
          <span className="eyebrow">每日巡检</span>
          <h1>每日简报</h1>
          <p>查看临期安排、当天备战任务与尚未报告的公开面经来源。</p>
        </div>
        <button className="button primary" type="button" disabled={loading} onClick={run}>
          <Play size={17} />
          {loading ? "正在巡检…" : hasToday ? "查看今日简报" : "生成今日简报"}
        </button>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="briefing-grid">
        <aside className="panel briefing-history">
          <strong>简报历史</strong>
          {items.length ? items.map((item) => (
            <button
              className={selected?.id === item.id ? "active" : ""}
              type="button"
              key={item.id}
              onClick={() => setSelected(item)}
            >
              {item.briefing_date}
            </button>
          )) : <p className="quiet-empty">暂无简报。</p>}
        </aside>
        <div className="panel briefing-content">
          {selected ? (
            <>
              <div className="section-title">
                <Bell size={21} />
                <div>
                  <h2>{selected.briefing_date} 简报</h2>
                  <span>生成于 {formatDateTime(selected.created_at)}</span>
                </div>
              </div>
              <section>
                <h3>需要留意</h3>
                {selected.payload.alerts.length ? selected.payload.alerts.map((item) => (
                  <p key={item.timeline_node_id}>
                    <Warning size={15} />
                    {item.title} · {formatDateTime(item.scheduled_at)} · {item.alert_types.join("、")}
                  </p>
                )) : <p>暂无临期、逾期或冲突安排。</p>}
              </section>
              <section>
                <h3>当天备战</h3>
                {selected.payload.today_tasks.length ? selected.payload.today_tasks.map((item) => (
                  <p key={item.task_id}>{item.title} · {formatDateTime(item.scheduled_at)}</p>
                )) : <p>当天没有待处理备战任务。</p>}
              </section>
              <section>
                <h3>新增公开来源</h3>
                {selected.payload.new_sources.length ? selected.payload.new_sources.map((item) => (
                  <p key={item.url}>
                    <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
                  </p>
                )) : <p>没有发现新的来源。</p>}
              </section>
              {selected.payload.search_errors.length > 0 && (
                <section>
                  <h3>搜索未完成</h3>
                  {selected.payload.search_errors.map((item) => (
                    <p key={item.application_id}>投递 #{item.application_id}：{item.message}</p>
                  ))}
                </section>
              )}
            </>
          ) : (
            <div className="empty-state">
              <Bell size={36} weight="duotone" />
              <strong>还没有每日简报</strong>
              <span>点击“生成今日简报”开始今天的本地巡检。</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
