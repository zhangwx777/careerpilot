import { ArrowClockwise, Brain, Check, ImageSquare, LinkSimple, PaperPlaneTilt, Sparkle, Trash } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { clearDraft, loadDraft, loadSessionId, saveDraft, saveSessionId } from "../drafts";
import { formatDateTime } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Application, IntelChatMessage, IntelDossier, IntelInsight, IntelPayload, IntelProgress, IntelRoundType, IntelSession, InterviewIntel, ProviderOption, SourceRecord } from "../types";

const rounds: IntelRoundType[] = ["测评", "笔试", "AI面", "一面", "二面", "三面", "HR面", "多轮综合", "未注明"];
const intelDraftKey = "qiuzhao-agent:intel-draft";
const activeIntelSessionKey = "qiuzhao-agent:intel-active-session";
type IntelTab = "input" | "summary" | "library";
type IntelDraft = { applicationId: number; provider: string; roundType: IntelRoundType | ""; paste: string; imageTexts: { name: string; text: string }[]; supplementWeb: boolean };
type Confirmation = { title: string; description: string; confirmLabel: string; onConfirm: () => void };

function loadIntelDraft(): IntelDraft {
  return loadDraft<IntelDraft>(window.localStorage, intelDraftKey, { applicationId: 0, provider: "", roundType: "", paste: "", imageTexts: [], supplementWeb: false });
}

function applicationLabel(application: Application) {
  return `${application.position.company.name} · ${application.position.title}`;
}

function SourceLinks({ sources }: { sources: Pick<SourceRecord, "id" | "title" | "url" | "kind" | "file_name">[] }) {
  return <div className="intel-source-links">{sources.map((source) => source.url ? <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><LinkSimple size={14} />{source.title}</a> : <span key={source.id}><LinkSimple size={14} />{source.file_name || source.title}</span>)}</div>;
}

function ProgressSources({ progress }: { progress: IntelProgress }) {
  return <div className="intel-progress" role="status"><div className="intel-progress-heading"><strong>{progress.stage}</strong><ArrowClockwise size={16} className="intel-progress-icon" /></div>{(progress.found !== undefined || progress.accepted !== undefined) && <div className="intel-progress-counts"><span>发现 {progress.found ?? 0}</span><span>采纳 {progress.accepted ?? 0}</span><span>排除 {progress.rejected ?? 0}</span></div>}{progress.sources.length > 0 && <SourceLinks sources={progress.sources} />}{(progress.errors ?? []).length > 0 && <div className="intel-progress-errors">{progress.errors?.map((item) => <p key={item}>{item}</p>)}</div>}</div>;
}

function InsightView({ insight, payload, onAsk }: { insight: IntelInsight; payload: IntelPayload; onAsk: (question: string) => void }) {
  if (insight.status === "未生成" || insight.status === "生成中" || insight.status === "暂无资料") return <div className="empty-state"><Brain size={40} weight="duotone" /><strong>{insight.status === "生成中" ? "正在生成岗位洞察" : insight.status === "暂无资料" ? "还没有面经材料" : "尚未生成岗位洞察"}</strong><span>确认面经后会从该岗位全部资料中提取共性方向和准备重点。</span></div>;
  if (insight.status === "失败") return <div className="notice error"><strong>岗位洞察生成失败</strong><p>{insight.error_message || "原始面经仍已保存。"}</p></div>;
  return <div className="intel-report">
    <section className="intel-report-lead"><span className="eyebrow">岗位面试概览</span><h2>{payload.summary?.value || "已收录面试资料"}</h2><p>{payload.difficulty ? `整体难度：${payload.difficulty.value}` : "洞察来自当前岗位的全部面经资料。"}</p></section>
    <section><div className="intel-section-heading"><h3>高频考察方向</h3><span>{insight.high_frequency_directions.length ? "按独立来源数排序" : "尚未形成多来源高频方向"}</span></div>{insight.high_frequency_directions.length ? <div className="intel-question-list">{insight.high_frequency_directions.map((item) => <article className="intel-question" key={item.title}><div><span className="intel-question-meta">{item.source_ids.length} 个来源 · {item.round_types.join("、") || "轮次未注明"}</span><strong>{item.title}</strong><p>{item.representative_questions.join("；") || "暂无代表问题"}</p></div></article>)}</div> : <p className="quiet-empty">至少积累两份独立来源后，这里会显示稳定的共性方向。</p>}</section>
    <section><div className="intel-section-heading"><h3>核心问题</h3><span>{insight.core_questions.length} 项</span></div>{insight.core_questions.length ? <div className="intel-question-list">{insight.core_questions.map((item) => <article className="intel-question" key={`${item.round_type}-${item.question}`}><div><span className="intel-question-meta">{item.category} · {item.round_type}</span><strong>{item.question}</strong><p>{item.reason}</p></div><button className="button text" type="button" onClick={() => onAsk(item.question)}>问 AI</button></article>)}</div> : <p className="quiet-empty">暂无核心问题。</p>}</section>
    <section><div className="intel-section-heading"><h3>面试流程</h3><span>{payload.rounds.length} 个轮次</span></div>{payload.rounds.length ? payload.rounds.map((round, index) => <article className="intel-round" key={`${round.round_type}-${index}`}><strong>{round.round_type}{round.duration_minutes ? ` · ${round.duration_minutes} 分钟` : ""}</strong><span>{round.question_types.map((item) => item.value).join("、") || "题型未明确"}</span><small>{round.focus_topics.map((item) => item.value).join("、") || "暂无明确考察重点"}</small></article>) : <p className="quiet-empty">暂无明确面试流程。</p>}</section>
    <section><div className="intel-section-heading"><h3>准备重点</h3><span>{insight.preparation_items.length} 项</span></div>{insight.preparation_items.length ? <div className="intel-preparation-list">{insight.preparation_items.map((item) => <article key={item.title}><strong>{item.title}</strong><p>{item.detail}</p></article>)}</div> : <p className="quiet-empty">暂无准备重点。</p>}</section>
  </div>;
}

function Materials({ items, roundFilter, onDelete }: { items: InterviewIntel[]; roundFilter: string; onDelete: (item: InterviewIntel) => void }) {
  const filtered = roundFilter === "全部" ? items : items.filter((item) => item.round_type === roundFilter);
  return <div className="intel-materials">{filtered.length ? filtered.map((item) => <details key={item.id} className="intel-material"><summary><div><strong>{item.title}</strong><span>{item.round_type} · {formatDateTime(item.created_at)} · {item.sources.length} 个来源</span></div><Trash size={16} /></summary><div className="intel-material-body"><div className="intel-material-actions"><span>本份材料内容</span><button className="button text danger-button" type="button" onClick={(event) => { event.preventDefault(); onDelete(item); }}>删除</button></div>{item.sources.map((source) => <article className="intel-material-source" key={source.id}><strong>{source.file_name || source.title}</strong>{source.url && <a href={source.url} target="_blank" rel="noreferrer">打开来源</a>}<p>{source.text || "没有可显示的原文。"}</p></article>)}{item.payload.questions.length > 0 && <><h4>本份材料提取的问题</h4><ul>{item.payload.questions.map((question) => <li key={question.question}>{question.question}</li>)}</ul></>}</div></details>) : <p className="quiet-empty">当前筛选下还没有面经材料。</p>}</div>;
}

async function readImage(file: File): Promise<{ name: string; mime_type: string; data_url: string }> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve({ name: file.name, mime_type: file.type, data_url: String(reader.result) }); reader.onerror = () => reject(new Error(`${file.name} 读取失败`)); reader.readAsDataURL(file); });
}

type ChatTurn = { user: IntelChatMessage | null; assistant: IntelChatMessage | null };

function groupChatMessages(messages: IntelChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const message of messages) {
    const last = turns[turns.length - 1];
    if (message.role === "user") turns.push({ user: message, assistant: null });
    else if (last && !last.assistant) last.assistant = message;
    else turns.push({ user: null, assistant: message });
  }
  return turns;
}

export function IntelPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = id ? Number(id) : null;
  const draft = useMemo(loadIntelDraft, []);
  const [applications, setApplications] = useState<Application[]>([]);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [applicationId, setApplicationId] = useState(draft.applicationId);
  const [provider, setProvider] = useState(draft.provider);
  const [roundType, setRoundType] = useState<IntelRoundType | "">(draft.roundType);
  const [paste, setPaste] = useState(draft.paste);
  const [imageTexts, setImageTexts] = useState(draft.imageTexts);
  const [supplementWeb, setSupplementWeb] = useState(draft.supplementWeb);
  const [session, setSession] = useState<IntelSession | null>(null);
  const [dossier, setDossier] = useState<IntelDossier | null>(null);
  const [chat, setChat] = useState<IntelChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [imageFiles, setImageFiles] = useState<File[]>([]);
  const [imagesRecognized, setImagesRecognized] = useState(imageTexts.length > 0);
  const [draggingImages, setDraggingImages] = useState(false);
  const [roundFilter, setRoundFilter] = useState("全部");
  const [insightVersion, setInsightVersion] = useState(0);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const rawTab = searchParams.get("tab");
  const activeTab: IntelTab = rawTab === "summary" || rawTab === "library" ? rawTab : "input";
  const selectTab = (next: IntelTab) => { const params = new URLSearchParams(searchParams); params.set("tab", next); setSearchParams(params); };

  useEffect(() => { let cancelled = false; api.applications.list({ page_size: 100 }).then((result) => { if (!cancelled) setApplications(result.items); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); }); api.providers.list().then((result) => { if (!cancelled) { setProviders(result); setProvider((current) => result.some((item) => item.name === current) ? current : result[0]?.name ?? ""); } }).catch((reason: Error) => { if (!cancelled) setError(reason.message); }); return () => { cancelled = true; }; }, []);
  useEffect(() => { saveDraft(window.localStorage, intelDraftKey, { applicationId, provider, roundType, paste, imageTexts, supplementWeb }); }, [applicationId, provider, roundType, paste, imageTexts, supplementWeb]);
  useEffect(() => { if (sessionId) return; const active = loadSessionId(window.localStorage, activeIntelSessionKey); if (active) { navigate(`/intel/${active}`, { replace: true }); return; } api.intel.sessions().then((items) => { if (items[0]) navigate(`/intel/${items[0].id}`, { replace: true }); }).catch(() => undefined); }, [navigate, sessionId]);
  useEffect(() => {
    if (!applicationId) {
      setDossier(null);
      setChat([]);
      return;
    }
    let cancelled = false;
    api.intel.dossier(applicationId)
      .then((next) => { if (!cancelled) setDossier(next); })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [applicationId, session?.status, insightVersion]);
  usePolling({
    enabled: Boolean(applicationId && dossier?.insight.status === "生成中"),
    interval: 1000,
    maxAttempts: 150,
    poll: async () => {
      if (!applicationId) return;
      setDossier(await api.intel.dossier(applicationId));
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "岗位洞察读取失败"),
  });
  useEffect(() => {
    if (!applicationId) return;
    let cancelled = false;
    api.intel.chatHistory(applicationId)
      .then((history) => { if (!cancelled) setChat(history); })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [applicationId]);
  usePolling({
    enabled: Boolean(applicationId && chat.some((item) => item.status === "生成中")),
    interval: 700,
    maxAttempts: 300,
    poll: async () => {
      if (!applicationId) return;
      setChat(await api.intel.chatHistory(applicationId));
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "问答状态读取失败"),
  });
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    api.intel.session(sessionId)
      .then((value) => {
        if (cancelled) return;
        if (value.status === "已丢弃") {
          clearDraft(window.localStorage, activeIntelSessionKey);
          setSession(null);
          navigate("/intel?tab=input", { replace: true });
          return;
        }
        setSession(value);
        setApplicationId(value.application_id);
        setRoundType(value.round_type);
        if (value.status === "聚合中" || value.status === "待裁决") saveSessionId(window.localStorage, activeIntelSessionKey, value.id);
        else clearDraft(window.localStorage, activeIntelSessionKey);
      })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [navigate, sessionId]);
  usePolling({
    enabled: Boolean(sessionId && (session?.status === "聚合中" || session?.status === "待裁决")),
    interval: 1200,
    maxAttempts: 150,
    poll: async () => {
      if (!sessionId) return;
      const value = await api.intel.session(sessionId);
      if (value.status === "已丢弃") {
        clearDraft(window.localStorage, activeIntelSessionKey);
        setSession(null);
        navigate("/intel?tab=input", { replace: true });
        return;
      }
      setSession(value);
      setApplicationId(value.application_id);
      setRoundType(value.round_type);
      if (value.status === "聚合中" || value.status === "待裁决") saveSessionId(window.localStorage, activeIntelSessionKey, value.id);
      else clearDraft(window.localStorage, activeIntelSessionKey);
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : "面经状态读取失败"),
  });
  useEffect(() => { const handler = (event: Event) => { setQuestion(String((event as CustomEvent<string>).detail)); selectTab("summary"); }; window.addEventListener("intel-question", handler); return () => window.removeEventListener("intel-question", handler); });

  async function extractImages() {
    if (!imageFiles.length) return;
    setUploading(true); setError("");
    try { const result = await api.intel.extractImages({ provider, images: await Promise.all(imageFiles.map(readImage)) }); setImageTexts(result.images); setImagesRecognized(true); } catch (reason) { setError(reason instanceof Error ? reason.message : "图片识别失败"); } finally { setUploading(false); }
  }
  function addImageFiles(files: File[]) { if (!files.length) return; if (imageFiles.length + files.length > 6 || files.some((file) => !["image/png", "image/jpeg", "image/webp"].includes(file.type))) { setError("最多上传 6 张 PNG、JPEG 或 WebP 图片"); return; } setImageFiles((current) => [...current, ...files]); setImagesRecognized(false); setImageTexts([]); setError(""); }
  function selectImageFiles(event: React.ChangeEvent<HTMLInputElement>) { addImageFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }
  function dropImageFiles(event: React.DragEvent<HTMLDivElement>) { event.preventDefault(); setDraggingImages(false); addImageFiles(Array.from(event.dataTransfer.files)); }
  async function submit() {
    if (!applicationId) { setError("请选择投递"); return; }
    if (!roundType) { setError("请选择这份资料所属轮次"); return; }
    if (imageFiles.length && !imagesRecognized) { setError("请先点击“识别截图”，确认识别结果后再开始分析"); return; }
    if (!paste.trim() && !imageTexts.some((item) => item.text.trim()) && !supplementWeb) { setError("请粘贴面经或识别截图，或开启联网补充"); return; }
    setLoading(true); setError("");
    try { const created = await api.intel.create({ application_id: applicationId, provider, round_type: roundType, user_paste: paste.trim() || null, image_texts: imageTexts.filter((item) => item.text.trim()), supplement_web: supplementWeb }); setSession(created); saveSessionId(window.localStorage, activeIntelSessionKey, created.id); navigate(`/intel/${created.id}?tab=input`, { replace: true }); } catch (reason) { setError(reason instanceof Error ? reason.message : "聚合失败"); } finally { setLoading(false); }
  }
  async function resolve() { if (!session || (session.conflicts ?? []).some((item) => !choices[item.field])) { setError("请为每项冲突选择一个候选结论"); return; } setLoading(true); setError(""); try { const done = await api.intel.resolve(session.id, choices); clearDraft(window.localStorage, activeIntelSessionKey); setSession(done); } catch (reason) { setError(reason instanceof Error ? reason.message : "裁决失败"); } finally { setLoading(false); } }
  async function discard() { if (!session) return; setLoading(true); setError(""); try { await api.intel.discard(session.id); clearDraft(window.localStorage, activeIntelSessionKey); setSession(null); navigate("/intel?tab=input", { replace: true }); } catch (reason) { setError(reason instanceof Error ? reason.message : "舍弃失败"); } finally { setLoading(false); } }
  async function rebuildInsight() { if (!applicationId) return; setLoading(true); setError(""); try { setDossier(await api.intel.rebuildDossier({ application_id: applicationId, provider })); } catch (reason) { setError(reason instanceof Error ? reason.message : "洞察生成失败"); } finally { setLoading(false); } }
  async function deleteMaterial(item: InterviewIntel) { setLoading(true); setError(""); try { await api.intel.deleteMaterial(item.id); setInsightVersion((current) => current + 1); } catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); } finally { setLoading(false); } }
  function askDiscard() { setConfirmation({ title: "舍弃此次面经分析？", description: "舍弃后不会写入岗位资料库。", confirmLabel: "舍弃此次分析", onConfirm: () => { setConfirmation(null); void discard(); } }); }
  function askDeleteMaterial(item: InterviewIntel) { setConfirmation({ title: "删除这份面经材料？", description: `删除“${item.title}”后会重新生成岗位洞察。`, confirmLabel: "删除材料", onConfirm: () => { setConfirmation(null); void deleteMaterial(item); } }); }
  async function ask() { if (!applicationId || !question.trim()) return; setLoading(true); setError(""); const asked = question.trim(); try { const result = await api.intel.chat({ application_id: applicationId, provider, question: asked }); setChat((current) => [...current, { id: Date.now(), role: "user", content: asked, status: "已完成", source_ids: [], created_at: new Date().toISOString() }, result.message]); setQuestion(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "问答失败"); } finally { setLoading(false); } }

  const isRunning = session?.status === "聚合中";
  const selectedApplication = applications.find((item) => item.id === applicationId);
  const sourceTitle = (sourceId: string) => dossier?.sources.find((source) => source.id === sourceId)?.title ?? sourceId;
  const chatTurns = groupChatMessages(chat);
  const inputView = <div className="intel-tab-grid"><aside className="intel-rail"><div className="panel intel-input-card"><div className="section-title"><Sparkle size={20} /><div><h2>新增面经</h2><span>先选择轮次，再录入文字或截图</span></div></div><label>所属轮次<select value={roundType} onChange={(event) => setRoundType(event.target.value as IntelRoundType | "")} disabled={isRunning}><option value="">请选择轮次</option>{rounds.map((round) => <option key={round} value={round}>{round}</option>)}</select></label><textarea rows={9} value={paste} onChange={(event) => setPaste(event.target.value)} disabled={isRunning} placeholder="粘贴面经、备忘录或面试题…" /><div className={`intel-upload-zone${draggingImages ? " is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDraggingImages(true); }} onDragLeave={() => setDraggingImages(false)} onDrop={dropImageFiles}><label className="upload-control"><ImageSquare size={18} />拖拽图片到这里，或点击选择<input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={selectImageFiles} disabled={uploading || isRunning} /></label>{imageFiles.length > 0 && <div className="intel-upload-files">{imageFiles.map((file, index) => <div className="intel-upload-file" key={`${file.name}-${index}`}><span title={file.name}>{file.name}</span><button type="button" onClick={() => { setImageFiles((current) => current.filter((_, fileIndex) => fileIndex !== index)); setImageTexts((current) => current.filter((_, textIndex) => textIndex !== index)); setImagesRecognized(false); }} disabled={uploading || isRunning}>移除</button></div>)}</div>}</div>{imageFiles.length > 0 && <button className="button ghost" type="button" onClick={extractImages} disabled={uploading || isRunning}>{uploading ? "正在识别截图…" : "识别截图"}</button>}{imageTexts.length > 0 && <div className="intel-image-texts"><strong>截图识别结果（可编辑）</strong>{imageTexts.map((item, index) => <label key={`${item.name}-${index}`}><span>{item.name}</span><textarea rows={5} value={item.text} onChange={(event) => setImageTexts((current) => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, text: event.target.value } : entry))} disabled={isRunning} /></label>)}</div>}<button className="button primary" disabled={loading || uploading || isRunning} onClick={submit}><Sparkle size={18} />{loading || isRunning ? "正在整理…" : "开始分析"}</button></div>{session?.progress_payload && <ProgressSources progress={session.progress_payload} />}{session?.status === "待裁决" && <div className="intel-conflicts"><p>这份资料可能包含岗位描述或不确定结论，请确认后写入岗位档案。</p>{session.conflicts?.map((item) => <label key={item.field}>“{item.field}”<select value={choices[item.field] ?? ""} onChange={(event) => setChoices({ ...choices, [item.field]: event.target.value })}><option value="">请选择候选结论</option>{item.candidates.map((candidate) => <option key={candidate.value} value={candidate.value}>{candidate.value}</option>)}</select></label>)}<div className="intel-conflict-actions"><button className="button primary" disabled={loading} onClick={resolve}><Check size={17} />确认并写入</button><button className="button ghost danger-button" disabled={loading} onClick={askDiscard}>舍弃此次分析</button></div></div>}{session?.status === "失败" && <div className="notice error">{session.error_message ?? "面经分析失败"}</div>}{session?.status === "已完成" && <div className="notice success">已写入岗位面经档案{dossier?.reminder ? `，准备提醒已安排在 ${formatDateTime(dossier.reminder.scheduled_at)}` : "；当前没有确定的未来面试，暂不推送提醒"}。</div>}</aside></div>;
  const summaryView = (
    <div className="intel-summary-layout">
      <main className="intel-main panel">
        <div className="intel-main-heading">
          <div>
            <span className="eyebrow">{dossier ? `${dossier.company_name} · ${dossier.position_title}` : "岗位级分析"}</span>
            <h2>面试洞察</h2>
          </div>
          {dossier?.reminder && <span className="intel-reminder-badge">准备提醒 · {formatDateTime(dossier.reminder.scheduled_at)}</span>}
        </div>
        {session?.status === "待裁决" && <p className="quiet-empty">资料正在等待确认，请回到“录入与进度”处理。</p>}
        {dossier ? (
          <>
            <InsightView insight={dossier.insight} payload={dossier.payload} onAsk={(asked) => setQuestion(asked)} />
            {(dossier.insight.status === "未生成" || dossier.insight.status === "失败") && (
              <button className="button ghost" type="button" disabled={loading} onClick={rebuildInsight}>
                {loading ? "正在生成…" : "生成岗位洞察"}
              </button>
            )}
          </>
        ) : (
          <div className="empty-state">
            <Brain size={40} weight="duotone" />
            <strong>选择一个投递开始</strong>
            <span>岗位的多份面经会自动形成岗位级洞察。</span>
          </div>
        )}
      </main>
      <aside className="panel intel-chat">
        <div className="section-title">
          <Brain size={20} />
          <div>
            <h2>面经问答</h2>
            <span>由 AI 结合面经和通用知识生成</span>
          </div>
        </div>
        <div className="intel-chat-history">
          {chatTurns.length ? chatTurns.map((turn) => {
            const answer = turn.assistant;
            const timestamp = turn.user?.created_at ?? answer?.created_at;
            return (
              <details className="intel-chat-turn" key={turn.user?.id ?? answer?.id}>
                <summary>
                  <span>{turn.user?.content || "AI 回答"}</span>
                  {timestamp && <small>{formatDateTime(timestamp)}</small>}
                </summary>
                <div className="intel-chat-turn-body">
                  {turn.user && (
                    <article className="intel-chat-message user">
                      <span>你</span>
                      <p>{turn.user.content}</p>
                    </article>
                  )}
                  {answer && (
                    <article className={`intel-chat-message assistant${answer.status === "生成中" ? " is-pending" : ""}`}>
                      <span>{answer.status === "生成中" ? "AI 正在生成" : "AI"}</span>
                      <p>{answer.content || (answer.status === "生成中" ? "正在生成回答…" : "暂无回答")}</p>
                      {answer.status === "失败" && <small>本次回答生成失败，可重新提问。</small>}
                      {answer.source_ids.length > 0 && <small>引用：{answer.source_ids.map(sourceTitle).join("、")}</small>}
                    </article>
                  )}
                  {!answer && <p className="quiet-empty">正在等待回答…</p>}
                </div>
              </details>
            );
          }) : <p className="quiet-empty">点核心问题的“问 AI”，或直接输入问题。</p>}
        </div>
        <div className="intel-chat-compose">
          <textarea rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这个岗位的 Agent 项目应该怎么准备？" />
          <button className="button primary" disabled={loading || !question.trim()} onClick={ask}>
            <PaperPlaneTilt size={17} />
            {loading ? "正在提交…" : "发送"}
          </button>
        </div>
      </aside>
    </div>
  );
  const libraryView = <section className="panel intel-library"><div className="section-title"><Brain size={20} /><div><h2>面经档案</h2><span>{dossier?.materials.length ?? 0} 份当前岗位的原始材料，可追溯分析依据</span></div></div><label className="intel-library-filter">轮次筛选<select value={roundFilter} onChange={(event) => setRoundFilter(event.target.value)}><option value="全部">全部</option>{rounds.map((round) => <option key={round} value={round}>{round}</option>)}</select></label><Materials items={dossier?.materials ?? []} roundFilter={roundFilter} onDelete={askDeleteMaterial} /></section>;
  return (
    <section className="intel-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">岗位面经资料 · 多源分析</span>
          <h1>面经工作台</h1>
          <p>先保存每份原始面经，再从全部资料中提取岗位级面试洞察。</p>
        </div>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="intel-context panel">
        <label>
          当前投递
          <select value={applicationId} onChange={(event) => setApplicationId(Number(event.target.value))} disabled={isRunning}>
            <option value={0}>选择投递</option>
            {applications.map((item) => <option key={item.id} value={item.id}>{applicationLabel(item)}</option>)}
          </select>
        </label>
        <label>
          分析模型
          <select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={isRunning}>
            {providers.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.model}</option>)}
          </select>
        </label>
        <label className="intel-toggle">
          <input type="checkbox" checked={supplementWeb} onChange={(event) => setSupplementWeb(event.target.checked)} disabled={isRunning} />
          联网补充
        </label>
        {selectedApplication && <span className="intel-context-note">资料会聚合到 {applicationLabel(selectedApplication)}</span>}
      </div>
      <nav className="intel-tabs" aria-label="面经工作台分区">
        {([["input", "录入与进度"], ["summary", "面试洞察"], ["library", "面经档案"]] as [IntelTab, string][]).map(([value, label]) => (
          <button key={value} type="button" className={activeTab === value ? "active" : ""} onClick={() => selectTab(value)}>
            {label}
          </button>
        ))}
      </nav>
      {activeTab === "input" && inputView}
      {activeTab === "summary" && summaryView}
      {activeTab === "library" && libraryView}
      <ConfirmDialog
        open={Boolean(confirmation)}
        title={confirmation?.title ?? ""}
        description={confirmation?.description ?? ""}
        confirmLabel={confirmation?.confirmLabel}
        onCancel={() => setConfirmation(null)}
        onConfirm={() => confirmation?.onConfirm()}
      />
    </section>
  );
}
