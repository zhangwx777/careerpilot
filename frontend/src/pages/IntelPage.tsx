import { Brain, Check, LinkSimple, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Application, InterviewIntel, IntelPayload, IntelSession } from "../types";

const providers = ["qwen", "openai", "anthropic", "deepseek"];

function Payload({ payload }: { payload: IntelPayload }) {
  return <div className="intel-payload">
    <div><strong>面试轮次</strong>{payload.rounds.length ? payload.rounds.map((round, i) => <p key={i}>{round.round_type}{round.duration_minutes ? ` · 约 ${round.duration_minutes} 分钟` : ""}：{round.question_types.map(x => x.value).join("、") || "题型未明确"}</p>) : <p>暂无可靠轮次信息</p>}</div>
    <div><strong>高频重点</strong><p>{payload.frequent_topics.map(x => x.value).join("、") || "暂无可靠重点"}</p></div>
    <div><strong>难度</strong><p>{payload.difficulty?.value ?? "暂无可靠难度评价"}</p></div>
  </div>;
}

export function IntelPage() {
  const { id } = useParams(); const navigate = useNavigate(); const sessionId = id ? Number(id) : null;
  const [applications, setApplications] = useState<Application[]>([]); const [applicationId, setApplicationId] = useState(0); const [provider, setProvider] = useState("qwen"); const [paste, setPaste] = useState(""); const [session, setSession] = useState<IntelSession | null>(null); const [items, setItems] = useState<InterviewIntel[]>([]); const [choices, setChoices] = useState<Record<string, string>>({}); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  useEffect(() => { api.applications.list({ page_size: 100 }).then(x => setApplications(x.items)).catch(e => setError(e.message)); }, []);
  useEffect(() => { if (!sessionId) return; api.intel.session(sessionId).then(value => { setSession(value); setApplicationId(value.application_id); }).catch(e => setError(e.message)); }, [sessionId]);
  useEffect(() => { if (applicationId) api.intel.list(applicationId).then(setItems).catch(e => setError(e.message)); }, [applicationId, session]);
  async function submit() { if (!applicationId) return setError("请选择投递"); setLoading(true); setError(""); try { const created = await api.intel.create({ application_id: applicationId, provider, user_paste: paste.trim() || null }); setSession(created); navigate(`/intel/${created.id}`, { replace: true }); } catch (e) { setError(e instanceof Error ? e.message : "聚合失败"); } finally { setLoading(false); } }
  async function resolve() { if (!session || (session.conflicts ?? []).some(x => !choices[x.field])) return setError("请为每项冲突选择一个候选结论"); setLoading(true); try { const done = await api.intel.resolve(session.id, choices); setSession(done); } catch (e) { setError(e instanceof Error ? e.message : "裁决失败"); } finally { setLoading(false); } }
  return <section><div className="page-heading"><div><span className="eyebrow">多源核对 · 人工裁决</span><h1>面经情报</h1><p>从公开面经和你的补充内容中提取可溯源的备战重点。</p></div></div>{error && <div className="notice error">{error}</div>}
    <div className="intel-grid"><div className="panel intel-form"><label>关联投递<select value={applicationId} onChange={e => setApplicationId(Number(e.target.value))}><option value="">选择投递</option>{applications.map(x => <option key={x.id} value={x.id}>{x.position.company.name} · {x.position.title}</option>)}</select></label><label>抽取 provider<select value={provider} onChange={e => setProvider(e.target.value)}>{providers.map(x => <option key={x}>{x}</option>)}</select></label><label>补充面经（可选）<textarea rows={8} value={paste} onChange={e => setPaste(e.target.value)} placeholder="粘贴你收集到的面经，系统会作为独立来源。" /></label><button className="button primary" disabled={loading} onClick={submit}><Sparkle size={18} />{loading ? "正在聚合…" : "开始聚合"}</button></div>
    <div className="panel intel-result"><div className="section-title"><Brain size={21}/><div><h2>结构化结果</h2><span>{session ? `会话 #${session.id} · ${session.status}` : "选择投递后发起聚合"}</span></div></div>{session?.draft_payload && <Payload payload={session.draft_payload} />}{session?.status === "待裁决" && <>{session.error_message && <p className="resolved-note">审查提示：{session.error_message}</p>}<div className="intel-conflicts">{session.conflicts?.map(x => <label key={x.field}>“{x.field}”<select value={choices[x.field] ?? ""} onChange={e => setChoices({ ...choices, [x.field]: e.target.value })}><option value="">请选择候选结论</option>{x.candidates.map(c => <option key={c.value} value={c.value}>{c.value}</option>)}</select></label>)}</div><button className="button primary" disabled={loading} onClick={resolve}><Check size={17}/>确认裁决并写入</button></>}{session?.status === "已完成" && <p className="resolved-note">已写入面经情报。</p>}</div></div>
    {items.map(item => <article className="panel intel-history" key={item.id}><div><strong>置信度 {item.confidence == null ? "—" : `${Math.round(item.confidence * 100)}%`}</strong><Payload payload={item.payload}/></div><aside><strong>来源</strong>{item.sources.map(source => source.url ? <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><LinkSimple size={14}/>{source.title}</a> : <span key={source.id}>{source.title}</span>)}</aside></article>)}</section>;
}
