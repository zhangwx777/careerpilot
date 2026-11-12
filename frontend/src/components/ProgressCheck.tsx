import { useEffect, useState } from "react";
import { api } from "../api";
import { formatDateTime } from "../format";
import { useRequestScope } from "../hooks/useRequestScope";
import type { ProgressCheckItem, StageChange } from "../types";

export function ProgressCheck({ onApplied }: { onApplied: () => void }) {
  const [items, setItems] = useState<ProgressCheckItem[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const capture = useRequestScope("progress-check");

  async function check() {
    const isCurrent = capture();
    setBusy(true); setError(""); setNotice(""); setSelected([]); setItems(null);
    try {
      const result = await api.applications.checkProgress();
      if (isCurrent()) setItems(result.items);
    } catch (reason) {
      if (isCurrent()) setError(reason instanceof Error ? reason.message : "进度检查失败");
    } finally { if (isCurrent()) setBusy(false); }
  }

  async function apply() {
    const isCurrent = capture();
    setBusy(true); setError("");
    try {
      const chosen = (items ?? []).filter((item) => selected.includes(item.application_id));
      const result = await api.applications.applyProgress(chosen.map(({ application_id, token }) => ({ application_id, token })));
      if (!isCurrent()) return;
      setItems(null); setSelected([]); setNotice(`已校正 ${result.applied_ids.length} 条投递进度。`);
      onApplied();
      window.dispatchEvent(new Event("preparation-task-updated"));
    } catch (reason) {
      if (isCurrent()) { setError(reason instanceof Error ? reason.message : "进度校正失败"); setItems(null); setSelected([]); }
    } finally { if (isCurrent()) setBusy(false); }
  }

  return <section className="progress-check" aria-label="历史进度检查" aria-busy={busy}>
    <div className="progress-check-toolbar"><button className="button ghost compact-button" type="button" onClick={() => void check()} disabled={busy}>{busy ? "正在处理…" : "检查进度"}</button><span>依据已确认的安排检查历史进度，选择后才会修改。</span></div>
    {error && <div className="notice error" role="alert">{error} 请重新检查进度。</div>}
    {notice && <p role="status">{notice}</p>}
    {items !== null && <div className="panel progress-check-results">
      <h2>进度检查结果</h2>
      <p>完成安排不等于通过该轮。若你已按实际情况手动调整，请保留当前阶段。</p>
      {items.length === 0 ? <p role="status">没有发现需要校正的投递。</p> : <>
        {items.map((item) => <label className="progress-check-row" key={item.application_id}>
          <input type="checkbox" disabled={busy} checked={selected.includes(item.application_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.application_id] : current.filter((id) => id !== item.application_id))} />
          <span><strong>{item.company_name} · {item.position_title}</strong><span>{item.current_status} → 建议 {item.suggested_status}</span><small>依据：{item.evidence.map((node) => `${node.node_type}（${node.status}，${formatDateTime(node.scheduled_at ?? node.ends_at)}）`).join("；")}</small></span>
        </label>)}
        <div className="progress-check-toolbar"><button className="button primary compact-button" type="button" disabled={busy || !selected.length} onClick={() => void apply()}>确认校正已选 {selected.length} 条</button><button className="button ghost compact-button" type="button" disabled={busy} onClick={() => { setItems(null); setSelected([]); }}>取消</button></div>
      </>}
    </div>}
  </section>;
}

export function StageHistory({ applicationId }: { applicationId: number }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<StageChange[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setItems(null); setError("");
    api.applications.stageHistory(applicationId).then((result) => { if (!cancelled) setItems(result.items); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [applicationId, open]);
  return <div className="stage-history">
    <button type="button" className="button ghost compact-button" aria-expanded={open} onClick={() => setOpen(!open)}>阶段记录</button>
    {open && <div>{error ? <p role="alert">{error}</p> : items === null ? <p role="status">正在读取阶段记录…</p> : !items.length ? <p>暂无阶段变更记录；历史变更来源不作推断。</p> : <ol>{items.map((item) => <li key={item.id}><strong>{item.from_status} → {item.to_status}</strong><span>{item.source} · {formatDateTime(item.created_at)}{item.timeline_node_id != null && ` · 节点 #${item.timeline_node_id}`}</span></li>)}</ol>}</div>}
  </div>;
}
