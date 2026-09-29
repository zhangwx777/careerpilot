import { ArrowClockwise, Brain, Check, CopySimple, ImageSquare, LinkSimple, PaperPlaneTilt, Sparkle, Trash } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ContextBar, StatusBadge } from "../components/DesignPrimitives";
import { clearDraft, loadDraft, loadSessionId, saveDraft, saveSessionId } from "../drafts";
import { formatDateTime } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Application, IntelChatMessage, IntelDossier, IntelInsight, IntelPayload, IntelProgress, IntelRoundType, IntelSession, InterviewIntel, SourceRecord } from "../types";

const rounds: IntelRoundType[] = ["测评", "笔试", "AI面", "一面", "二面", "三面", "HR面", "多轮综合", "未注明"];
const intelDraftKey = "qiuzhao-agent:intel-draft";
const activeIntelSessionKey = "qiuzhao-agent:intel-active-session";
type IntelTab = "input" | "library";
type IntelDraft = { applicationId: number; roundType: IntelRoundType | ""; paste: string; imageTexts: { name: string; text: string }[] };
type IntelImageAttachment = { file: File; previewUrl: string };
type Confirmation = { title: string; description: string; confirmLabel: string; onConfirm: () => void };

function loadIntelDraft(): IntelDraft {
  return loadDraft<IntelDraft>(window.localStorage, intelDraftKey, { applicationId: 0, roundType: "", paste: "", imageTexts: [] });
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
  if (insight.status === "未生成" || insight.status === "生成中" || insight.status === "暂无资料") return <div className="empty-state"><Brain size={40} weight="duotone" /><strong>{insight.status === "生成中" ? "正在生成岗位洞察" : insight.status === "暂无资料" ? "还没有面经材料" : "尚未生成岗位洞察"}</strong><span>从该岗位已有面经中整理共性方向、核心问题和轮次概览。</span></div>;
  if (insight.status === "失败") return <div className="notice error"><strong>岗位洞察生成失败</strong><p>{insight.error_message || "原始面经仍已保存。"}</p></div>;
  return <div className="intel-report">
    <section className="intel-report-lead"><span className="eyebrow">岗位面试概览</span><h2>{payload.summary?.value || "已收录面试资料"}</h2><p>{payload.difficulty ? `整体难度：${payload.difficulty.value}` : "洞察来自当前岗位的全部面经资料。"}</p></section>
    <section><div className="intel-section-heading"><h3>高频考察方向</h3><span>{insight.high_frequency_directions.length ? "按独立来源数排序" : "尚未形成多来源高频方向"}</span></div>{insight.high_frequency_directions.length ? <div className="intel-question-list">{insight.high_frequency_directions.map((item) => <article className="intel-question" key={item.title}><div><span className="intel-question-meta">{item.source_ids.length} 个来源 · {item.round_types.join("、") || "轮次未注明"}</span><strong>{item.title}</strong><p>{item.representative_questions.join("；") || "暂无代表问题"}</p></div></article>)}</div> : <p className="quiet-empty">至少积累两份独立来源后，这里会显示稳定的共性方向。</p>}</section>
    <section><div className="intel-section-heading"><h3>核心问题</h3><span>{insight.core_questions.length} 项</span></div>{insight.core_questions.length ? <div className="intel-question-list">{insight.core_questions.map((item) => <article className="intel-question" key={`${item.round_type}-${item.question}`}><div><span className="intel-question-meta">{item.category} · {item.round_type}</span><strong>{item.question}</strong><p>{item.reason}</p></div><button className="button text" type="button" onClick={() => onAsk(item.question)}>问 AI</button></article>)}</div> : <p className="quiet-empty">暂无核心问题。</p>}</section>
    <section><div className="intel-section-heading"><h3>轮次概览</h3><span>{payload.rounds.length} 个轮次</span></div>{payload.rounds.length ? payload.rounds.map((round, index) => <article className="intel-round" key={`${round.round_type}-${index}`}><strong>{round.round_type}{round.duration_minutes ? ` · ${round.duration_minutes} 分钟` : ""}</strong><span>题型：{round.question_types.map((item) => item.value).join("、") || "未明确"}</span><small>考察主题：{round.focus_topics.map((item) => item.value).join("、") || "未明确"}</small></article>) : <p className="quiet-empty">暂无明确面试轮次。</p>}</section>
  </div>;
}

function Materials({ items, onDelete }: { items: InterviewIntel[]; onDelete: (item: InterviewIntel) => void }) {
  return <div className="intel-materials">{items.length ? items.map((item) => <details key={item.id} className="intel-material"><summary><div><strong>{item.title}</strong><span>{item.round_type} · {formatDateTime(item.created_at)} · {item.sources.length} 个来源</span></div><Trash size={16} /></summary><div className="intel-material-body"><div className="intel-material-actions"><span>本份材料内容</span><button className="button text danger-button" type="button" onClick={(event) => { event.preventDefault(); onDelete(item); }}>删除</button></div>{item.sources.map((source) => <article className="intel-material-source" key={source.id}><strong>{source.file_name || source.title}</strong>{source.url && <a href={source.url} target="_blank" rel="noreferrer">打开来源</a>}<p>{source.text || "没有可显示的原文。"}</p></article>)}{item.payload.questions.length > 0 && <><h4>本份材料提取的问题</h4><ul>{item.payload.questions.map((question) => <li key={question.question}>{question.question}</li>)}</ul></>}</div></details>) : <p className="quiet-empty">当前岗位还没有面经档案。</p>}</div>;
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
  const [applicationId, setApplicationId] = useState(draft.applicationId);
  const [roundType, setRoundType] = useState<IntelRoundType | "">(draft.roundType);
  const [paste, setPaste] = useState(draft.paste);
  const [imageTexts, setImageTexts] = useState(draft.imageTexts);
  const [searchConfigured, setSearchConfigured] = useState(false);
  const [session, setSession] = useState<IntelSession | null>(null);
  const [dossier, setDossier] = useState<IntelDossier | null>(null);
  const [chat, setChat] = useState<IntelChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [imageFiles, setImageFiles] = useState<IntelImageAttachment[]>([]);
  const imagePreviewUrls = useRef(new Set<string>());
  const [imagesRecognized, setImagesRecognized] = useState(imageTexts.length > 0);
  const [insightVersion, setInsightVersion] = useState(0);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const chatLauncherRef = useRef<HTMLButtonElement>(null);
  const chatQuestionRef = useRef<HTMLTextAreaElement>(null);
  const chatHistoryRef = useRef<HTMLDivElement>(null);
  const chatHasOpened = useRef(false);
  const rawTab = searchParams.get("tab");
  const activeTab: IntelTab = rawTab === "library" ? "library" : "input";
  const selectTab = (next: IntelTab) => { const params = new URLSearchParams(searchParams); params.set("tab", next); setSearchParams(params); };
  function openChat(prefill?: string) {
    if (prefill !== undefined) setQuestion(prefill);
    setChatOpen(true);
  }

  useEffect(() => {
    if (chatOpen) {
      chatHasOpened.current = true;
      chatQuestionRef.current?.focus();
    } else if (chatHasOpened.current && activeTab === "input") {
      chatLauncherRef.current?.focus();
    }
  }, [activeTab, chatOpen]);

  useEffect(() => {
    if (!chatOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setChatOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [chatOpen]);

  useEffect(() => () => {
    for (const previewUrl of imagePreviewUrls.current) URL.revokeObjectURL(previewUrl);
    imagePreviewUrls.current.clear();
  }, []);

  useEffect(() => { let cancelled = false; api.applications.list({ page_size: 100 }).then((result) => { if (!cancelled) setApplications(result.items); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); }); api.search.get().then((result) => { if (!cancelled) setSearchConfigured(result.configured); }).catch(() => undefined); return () => { cancelled = true; }; }, []);
  useEffect(() => { saveDraft(window.localStorage, intelDraftKey, { applicationId, roundType, paste, imageTexts }); }, [applicationId, roundType, paste, imageTexts]);
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
        setChat([]);
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
  useEffect(() => { const handler = (event: Event) => { selectTab("input"); openChat(String((event as CustomEvent<string>).detail)); }; window.addEventListener("intel-question", handler); return () => window.removeEventListener("intel-question", handler); });

  async function extractImages() {
    if (!imageFiles.length) return;
    setUploading(true); setError("");
    try { const result = await api.intel.extractImages({ images: await Promise.all(imageFiles.map(({ file }) => readImage(file))) }); setImageTexts(result.images); setImagesRecognized(true); } catch (reason) { setError(reason instanceof Error ? reason.message : "图片识别失败"); } finally { setUploading(false); }
  }
  function addImageFiles(files: File[]) {
    if (!files.length) return;
    if (imageFiles.length + files.length > 6 || files.some((file) => !["image/png", "image/jpeg", "image/webp"].includes(file.type))) { setError("最多上传 6 张 PNG、JPEG 或 WebP 图片"); return; }
    const attachments = files.map((file) => {
      const previewUrl = URL.createObjectURL(file);
      imagePreviewUrls.current.add(previewUrl);
      return { file, previewUrl };
    });
    setImageFiles((current) => [...current, ...attachments]);
    setImagesRecognized(false);
    setImageTexts([]);
    setError("");
  }
  function selectImageFiles(event: React.ChangeEvent<HTMLInputElement>) { addImageFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }
  function pasteImageFiles(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null)
      .map((file, index) => file.name ? file : new File([file], `粘贴图片-${Date.now()}-${index}`, { type: file.type }));
    if (!files.length) return;
    event.preventDefault();
    const pastedText = event.clipboardData.getData("text/plain");
    if (pastedText) {
      const textarea = event.currentTarget;
      textarea.setRangeText(pastedText, textarea.selectionStart, textarea.selectionEnd, "end");
      setPaste(textarea.value);
    }
    addImageFiles(files);
  }
  function dropImageFiles(event: React.DragEvent<HTMLDivElement>) { event.preventDefault(); addImageFiles(Array.from(event.dataTransfer.files)); }
  function removeImageFile(index: number) {
    const attachment = imageFiles[index];
    if (!attachment) return;
    URL.revokeObjectURL(attachment.previewUrl);
    imagePreviewUrls.current.delete(attachment.previewUrl);
    setImageFiles((current) => current.filter((_, fileIndex) => fileIndex !== index));
    setImageTexts((current) => current.filter((_, textIndex) => textIndex !== index));
    setImagesRecognized(false);
  }
  async function submit() {
    if (!applicationId) { setError("请选择投递"); return; }
    if (!roundType) { setError("请选择这份资料所属轮次"); return; }
    if (imageFiles.length && !imagesRecognized) { setError("请先点击“识别截图”，确认识别结果后再开始分析"); return; }
    if (!paste.trim() && !imageTexts.some((item) => item.text.trim()) && !searchConfigured) { setError("请粘贴面经或识别截图，或先在模型设置中配置公开检索 Key"); return; }
    setLoading(true); setError("");
    try { const created = await api.intel.create({ application_id: applicationId, round_type: roundType, user_paste: paste.trim() || null, image_texts: imageTexts.filter((item) => item.text.trim()) }); setSession(created); saveSessionId(window.localStorage, activeIntelSessionKey, created.id); navigate(`/intel/${created.id}?tab=input`, { replace: true }); } catch (reason) { setError(reason instanceof Error ? reason.message : "聚合失败"); } finally { setLoading(false); }
  }
  async function resolve() { if (!session || (session.conflicts ?? []).some((item) => !choices[item.field])) { setError("请为每项冲突选择一个候选结论"); return; } setLoading(true); setError(""); try { const done = await api.intel.resolve(session.id, choices); clearDraft(window.localStorage, activeIntelSessionKey); setSession(done); } catch (reason) { setError(reason instanceof Error ? reason.message : "裁决失败"); } finally { setLoading(false); } }
  async function discard() { if (!session) return; setLoading(true); setError(""); try { await api.intel.discard(session.id); clearDraft(window.localStorage, activeIntelSessionKey); setSession(null); navigate("/intel?tab=input", { replace: true }); } catch (reason) { setError(reason instanceof Error ? reason.message : "舍弃失败"); } finally { setLoading(false); } }
  async function retrySession() { if (!session) return; setLoading(true); setError(""); try { const next = await api.intel.retry(session.id); setSession(next); saveSessionId(window.localStorage, activeIntelSessionKey, next.id); } catch (reason) { setError(reason instanceof Error ? reason.message : "重试失败"); } finally { setLoading(false); } }
  async function rebuildInsight() { if (!applicationId) return; setLoading(true); setError(""); try { setDossier(await api.intel.rebuildDossier({ application_id: applicationId })); } catch (reason) { setError(reason instanceof Error ? reason.message : "洞察生成失败"); } finally { setLoading(false); } }
  async function deleteMaterial(item: InterviewIntel) { setLoading(true); setError(""); try { await api.intel.deleteMaterial(item.id); setInsightVersion((current) => current + 1); } catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); } finally { setLoading(false); } }
  function askDiscard() { setConfirmation({ title: "舍弃此次面经分析？", description: "舍弃后不会写入岗位资料库。", confirmLabel: "舍弃此次分析", onConfirm: () => { setConfirmation(null); void discard(); } }); }
  function askDeleteMaterial(item: InterviewIntel) { setConfirmation({ title: "删除这份面经材料？", description: `删除“${item.title}”后会重新生成岗位洞察。`, confirmLabel: "删除材料", onConfirm: () => { setConfirmation(null); void deleteMaterial(item); } }); }
  async function ask() { if (!applicationId || !question.trim()) return; setLoading(true); setError(""); const asked = question.trim(); try { const result = await api.intel.chat({ application_id: applicationId, question: asked }); setChat((current) => [...current, { id: Date.now(), role: "user", content: asked, status: "已完成", source_ids: [], created_at: new Date().toISOString() }, result.message]); setQuestion(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "问答失败"); } finally { setLoading(false); } }
  async function copyAnswer(answer: IntelChatMessage) { try { await navigator.clipboard.writeText(answer.content); setCopiedMessageId(answer.id); } catch { setError("复制失败，请检查浏览器剪贴板权限"); } }
  async function deleteChatTurn(turn: ChatTurn) {
    if (!applicationId || !turn.user || !turn.assistant || turn.assistant.status === "生成中") return;
    setLoading(true); setError("");
    try {
      await api.intel.deleteChatTurn(applicationId, turn.user.id, turn.assistant.id);
      setChat((current) => current.filter((message) => message.id !== turn.user?.id && message.id !== turn.assistant?.id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "删除问答失败"); }
    finally { setLoading(false); }
  }
  async function clearChatHistory() {
    if (!applicationId) return;
    setLoading(true); setError("");
    try { await api.intel.clearChatHistory(applicationId); setChat([]); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "清空问答历史失败"); }
    finally { setLoading(false); }
  }
  function askDeleteChatTurn(turn: ChatTurn) {
    setConfirmation({
      title: "删除这条问答？",
      description: `问题和回答会从当前岗位历史中删除：${turn.user?.content.slice(0, 80) ?? "这条问答"}`,
      confirmLabel: "删除问答",
      onConfirm: () => { setConfirmation(null); void deleteChatTurn(turn); },
    });
  }
  function askClearChatHistory() {
    setConfirmation({
      title: "清空当前岗位的问答历史？",
      description: "当前岗位下的所有问题和回答都会删除，面经档案不会受影响。",
      confirmLabel: "清空历史",
      onConfirm: () => { setConfirmation(null); void clearChatHistory(); },
    });
  }

  const isRunning = session?.status === "聚合中";
  const selectedApplication = applications.find((item) => item.id === applicationId);
  const sourceTitle = (sourceId: string, message?: IntelChatMessage) => message?.sources?.find((source) => source.id === sourceId)?.title ?? dossier?.sources.find((source) => source.id === sourceId)?.title ?? sourceId;
  const chatTurns = groupChatMessages(chat);
  const latestChatMessage = chat[chat.length - 1];
  useEffect(() => {
    if (chatOpen && chatHistoryRef.current) {
      chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight;
    }
  }, [chatOpen, latestChatMessage?.id, latestChatMessage?.content, latestChatMessage?.status]);
  const inputCard = (
    <div className="panel intel-input-card">
      <div className="section-title"><Sparkle size={20} /><div><h2>新增面经</h2><span>选择轮次并录入面经内容</span></div></div>
      <label>所属轮次<select value={roundType} onChange={(event) => setRoundType(event.target.value as IntelRoundType | "")} disabled={isRunning}><option value="">请选择轮次</option>{rounds.map((round) => <option key={round} value={round}>{round}</option>)}</select></label>
      <div className="intel-composer" onDragOver={(event) => event.preventDefault()} onDrop={dropImageFiles}>
        {imageFiles.length > 0 && <div className="intel-image-previews">{imageFiles.map((attachment, index) => <div className="intel-image-preview" key={attachment.previewUrl}><img src={attachment.previewUrl} alt={attachment.file.name || "面经截图"} /><button type="button" aria-label={`移除 ${attachment.file.name || "图片"}`} onClick={() => removeImageFile(index)} disabled={uploading || isRunning}>×</button></div>)}</div>}
        <textarea rows={8} value={paste} onChange={(event) => setPaste(event.target.value)} onPaste={pasteImageFiles} disabled={isRunning} placeholder="粘贴面经、备忘录或面试题…" />
        <div className="intel-composer-actions">
          <label className="intel-attach-button"><ImageSquare size={19} /><input type="file" accept="image/png,image/jpeg,image/webp" multiple aria-label="添加图片" onChange={selectImageFiles} disabled={uploading || isRunning} /></label>
          {imageFiles.length > 0 && <button className="button ghost" type="button" onClick={extractImages} disabled={uploading || isRunning}>{uploading ? "正在识别…" : "识别图片"}</button>}
          <button className="button primary" disabled={loading || uploading || isRunning} onClick={submit}><Sparkle size={18} />{loading || isRunning ? "正在整理…" : "开始分析"}</button>
        </div>
      </div>
      {imageTexts.length > 0 && <div className="intel-image-texts"><strong>识别文字（可编辑）</strong>{imageTexts.map((item, index) => <label key={`${item.name}-${index}`}><span>{item.name}</span><textarea rows={5} value={item.text} onChange={(event) => setImageTexts((current) => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, text: event.target.value } : entry))} disabled={isRunning} /></label>)}</div>}
    </div>
  );
  const inputStatus = (
    <div className="intel-workbench-status">
      {session?.progress_payload && <ProgressSources progress={session.progress_payload} />}
      {session?.status === "待裁决" && <div className="intel-conflicts"><p>这份资料可能包含岗位描述或不确定结论，请确认后写入岗位档案。</p>{session.conflicts?.map((item) => <label key={item.field}>“{item.field}”<select value={choices[item.field] ?? ""} onChange={(event) => setChoices({ ...choices, [item.field]: event.target.value })}><option value="">请选择候选结论</option>{item.candidates.map((candidate) => <option key={candidate.value} value={candidate.value}>{candidate.value}</option>)}</select></label>)}<div className="intel-conflict-actions"><button className="button primary" disabled={loading} onClick={resolve}><Check size={17} />确认并写入</button><button className="button ghost danger-button" disabled={loading} onClick={askDiscard}>舍弃此次分析</button></div></div>}
      {session?.status === "失败" && <div className="notice error"><span>{session.error_message ?? "面经分析失败"}</span><button className="button ghost compact-button" type="button" disabled={loading} onClick={() => void retrySession()}>重试</button></div>}
      {session?.status === "已完成" && <div className="notice success">已写入岗位面经档案{dossier?.reminder ? `，准备提醒已安排在 ${formatDateTime(dossier.reminder.scheduled_at)}` : "；当前没有确定的未来面试，暂不推送提醒"}。</div>}
    </div>
  );
  const insightPanel = (
    <main className="intel-main panel">
      <div className="intel-main-heading">
        <div><span className="eyebrow">{selectedApplication ? applicationLabel(selectedApplication) : "岗位级分析"}</span><h2>岗位洞察</h2></div>
        {dossier?.reminder && <span className="intel-reminder-badge">准备提醒 · {formatDateTime(dossier.reminder.scheduled_at)}</span>}
      </div>
      {!applicationId ? <p className="quiet-empty">选择投递后查看该岗位的面经洞察。</p> : !dossier ? <p className="quiet-empty">正在读取岗位面经资料…</p> : dossier.materials.length === 0 ? (
        <div className="intel-insight-empty"><strong>还没有面经材料</strong><span>录入并确认一份面经后，这里会生成岗位洞察。</span></div>
      ) : (
        <>
          {session?.status === "待裁决" && <p className="quiet-empty">这份新资料确认后会加入岗位洞察。</p>}
          <InsightView insight={dossier.insight} payload={dossier.payload} onAsk={openChat} />
          {(dossier.insight.status === "未生成" || dossier.insight.status === "失败") && <button className="button ghost" type="button" disabled={loading} onClick={rebuildInsight}>{loading ? "正在生成…" : dossier.insight.status === "失败" ? "重试生成" : "生成岗位洞察"}</button>}
        </>
      )}
    </main>
  );
  const chatPortal = activeTab === "input" ? createPortal(
    <>
      <button
        ref={chatLauncherRef}
        className="button primary intel-chat-launcher"
        type="button"
        aria-haspopup="dialog"
        aria-expanded={chatOpen}
        aria-controls="intel-chat-window"
        aria-label={chatOpen ? "关闭面经问答" : "打开面经问答"}
        onClick={() => setChatOpen((current) => !current)}
      >
        <Brain size={19} />
        <span>面经问答</span>
      </button>
      <aside
        id="intel-chat-window"
        className="panel intel-chat-window"
        role="dialog"
        aria-modal="false"
        aria-labelledby="intel-chat-title"
        aria-hidden={!chatOpen}
        hidden={!chatOpen}
      >
        <div className="intel-chat-header">
          <div className="section-title">
            <Brain size={20} />
            <div>
              <h2 id="intel-chat-title">面经问答</h2>
              <span>由 AI 结合面经和通用知识生成</span>
            </div>
          </div>
          {chat.length > 0 && <button className="intel-chat-clear" type="button" onClick={askClearChatHistory} disabled={loading || chat.some((message) => message.status === "生成中")}>清空历史</button>}
          <button className="intel-chat-close" type="button" aria-label="关闭面经问答" onClick={() => setChatOpen(false)}>×</button>
        </div>
        <div ref={chatHistoryRef} className="intel-chat-history" tabIndex={0} role="log" aria-label="面经问答历史">
          {chatTurns.length ? chatTurns.map((turn) => {
            const answer = turn.assistant;
            const timestamp = turn.user?.created_at ?? answer?.created_at;
            return (
              <article className="intel-chat-turn" key={turn.user?.id ?? answer?.id}>
                <div className="intel-chat-turn-heading">
                  <strong>{turn.user?.content || "AI 回答"}</strong>
                  {timestamp && <small>{formatDateTime(timestamp)}</small>}
                  {turn.user && answer && answer.status !== "生成中" && <button className="intel-chat-delete-turn" type="button" aria-label="删除这条问答" title="删除这条问答" onClick={() => askDeleteChatTurn(turn)} disabled={loading}><Trash size={15} /></button>}
                </div>
                <div className="intel-chat-turn-body">
                  {turn.user && (
                    <article className="intel-chat-message user">
                      <span>你</span>
                      <p>{turn.user.content}</p>
                    </article>
                  )}
                  {answer && (
                    <article className={`intel-chat-message assistant${answer.status === "生成中" ? " is-pending" : ""}`}>
                      <span>{answer.status === "生成中" ? (answer.agent_stage || "AI 正在生成") : "AI"}</span>
                      <p>{answer.content || (answer.status === "生成中" ? "正在生成回答…" : "暂无回答")}</p>
                      {answer.status === "失败" && <small className="intel-chat-error">{answer.error_message || "本次回答生成失败，可重新提问。"}</small>}
                      {answer.degraded && <small className="intel-chat-warning">本次资料读取未完成，回答可能不完整。</small>}
                      {answer.insufficient_data && <small className="intel-chat-warning">当前岗位资料不足，以上内容包含不确定性。</small>}
                      {answer.search_status === "failed" && <small className="intel-chat-warning">公开检索失败，回答未将搜索结果视为已完成。</small>}
                      {(answer.used_tools?.length ?? 0) > 0 && <small>已读取：{answer.used_tools?.join("、")}</small>}
                      {answer.source_ids.length > 0 && <small>引用：{answer.source_ids.map((sourceId) => sourceTitle(sourceId, answer)).join("、")}</small>}
                      {answer.content && answer.status !== "生成中" && <button className="intel-chat-copy" type="button" onClick={() => void copyAnswer(answer)}><CopySimple size={14} />{copiedMessageId === answer.id ? "已复制" : "复制回答"}</button>}
                    </article>
                  )}
                  {!answer && <p className="quiet-empty">正在等待回答…</p>}
                </div>
              </article>
            );
          }) : <p className="quiet-empty">点核心问题的“问 AI”，或直接输入问题。</p>}
        </div>
        <div className="intel-chat-compose">
          <textarea ref={chatQuestionRef} rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="输入面经问题" placeholder="例如：这个岗位的 Agent 项目应该怎么准备？" />
          <button className="button primary" type="button" disabled={loading || !question.trim()} onClick={ask}>
            <PaperPlaneTilt size={17} />
            {loading ? "正在提交…" : "发送"}
          </button>
        </div>
      </aside>
    </>,
    document.body,
  ) : null;
  const inputView = (
    <div className="intel-workbench">
      <div className="intel-workbench-entry">{inputCard}{inputStatus}</div>
      {insightPanel}
    </div>
  );
  const libraryView = <section className="panel intel-library"><div className="section-title"><Brain size={20} /><div><h2>全部档案</h2><span>{dossier?.materials.length ?? 0} 份当前岗位的原始材料，按所属轮次标注，可追溯分析依据</span></div></div><Materials items={dossier?.materials ?? []} onDelete={askDeleteMaterial} /></section>;
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
      <ContextBar className="intel-context">
        <label>
          当前投递
          <select value={applicationId} onChange={(event) => { setChat([]); setApplicationId(Number(event.target.value)); }} disabled={isRunning}>
            <option value={0}>选择投递</option>
            {applications.map((item) => <option key={item.id} value={item.id}>{applicationLabel(item)}</option>)}
          </select>
        </label>
        <span className="intel-context-note">已按当前设置自动选择分析模型</span>
        <StatusBadge tone={searchConfigured ? "ready" : "neutral"}>{searchConfigured ? "公开检索已启用" : "当前为本地资料模式"}</StatusBadge>
        {selectedApplication && <span className="intel-context-note">资料会聚合到 {applicationLabel(selectedApplication)}</span>}
      </ContextBar>
      <nav className="intel-tabs" aria-label="面经工作台分区">
        {([["input", "工作台"], ["library", "全部档案"]] as [IntelTab, string][]).map(([value, label]) => (
          <button key={value} type="button" className={activeTab === value ? "active" : ""} onClick={() => selectTab(value)}>
            {label}
          </button>
        ))}
      </nav>
      {activeTab === "input" && inputView}
      {activeTab === "library" && libraryView}
      {chatPortal}
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
