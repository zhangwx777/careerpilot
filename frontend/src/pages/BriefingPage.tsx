import { Bell, Play, Sparkle, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { api } from "../api";
import { ContextBar, StatusBadge } from "../components/DesignPrimitives";
import { formatDateTime } from "../format";
import type { DailyBriefing } from "../types";

export function BriefingPage() {
  const [items, setItems] = useState<DailyBriefing[]>([]);
  const [selected, setSelected] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const today = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
  useEffect(() => { Promise.all([api.briefings.list({ page_size: 30 }), api.briefings.list({ briefing_date: today })]).then(([history, current]) => { setItems(history.items); setSelected(current.items[0] ?? history.items[0] ?? null); }).catch((reason: Error) => setError(reason.message)); }, [today]);
  const hasToday = items.some((item) => item.briefing_date === today);
  async function run() { setLoading(true); setError(""); try { const result = await api.briefings.run(); setSelected(result); setItems((current) => [result, ...current.filter((item) => item.id !== result.id)]); } catch (reason) { setError(reason instanceof Error ? reason.message : "简报生成失败"); } finally { setLoading(false); } }
  async function analyze() { if (!selected) return; setLoading(true); setError(""); try { const result = await api.briefings.analyze(selected.id); setSelected(result); setItems((current) => current.map((item) => item.id === result.id ? result : item)); } catch (reason) { setError(reason instanceof Error ? reason.message : "简报分析失败"); } finally { setLoading(false); } }
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
      <ContextBar className="briefing-toolbar"><label>查看日期<select value={selected?.id ?? ""} onChange={(event) => setSelected(items.find((item) => item.id === Number(event.target.value)) ?? null)}><option value="" disabled>选择日期</option>{items.map((item) => <option key={item.id} value={item.id}>{item.briefing_date}{item.briefing_date === today ? " · 今天" : ""}</option>)}</select></label><span>{items.length ? `已保存 ${items.length} 份简报` : "暂无历史简报"}</span></ContextBar>
      <div className="briefing-grid">
        <div className="panel briefing-content">
          {selected ? (
            <>
              <div className="section-title">
                <Bell size={21} />
                <div>
                  <h2>{selected.briefing_date} 简报</h2>
                  <span>生成于 {formatDateTime(selected.created_at)} · 记录生成当时的信息</span>
                </div>
                <StatusBadge tone={selected.payload.analysis_status === "已完成" ? "ready" : selected.payload.analysis_status === "失败" ? "danger" : "neutral"}>{selected.payload.analysis_status ? selected.payload.analysis_status === "失败" ? "AI 分析失败" : `AI 分析${selected.payload.analysis_status}` : "历史简报，无 AI 分析"}</StatusBadge>
              </div>
              {selected.payload.analysis_status === "失败" && <button className="button ghost compact-button" type="button" disabled={loading} onClick={() => void analyze()}><Sparkle size={15} />重新分析</button>}
              {selected.payload.analysis?.summary && <section className="briefing-analysis-summary"><h3>简报判断</h3><p>{selected.payload.analysis.summary}</p></section>}
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
                  <article className="briefing-source-card" key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a><small>{item.company_name && `${item.company_name} · `}{item.position_title}</small>{item.snippet && <p>{item.snippet}</p>}{selected.payload.analysis?.items?.find((analysis) => analysis.url === item.url) && <span className="briefing-source-judgement">{(() => { const judgement = selected.payload.analysis?.items?.find((analysis) => analysis.url === item.url); return judgement ? `${judgement.value === "high" ? "高价值" : judgement.value === "medium" ? "可参考" : "低价值"} · ${judgement.relation === "both" ? "面试与备战相关" : judgement.relation === "interview" ? "与面试相关" : judgement.relation === "preparation" ? "与备战相关" : "暂不相关"}：${judgement.reason}` : ""; })()}</span>}</article>
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
