export interface ProviderOption {
  name: string;
  label: string;
  description: string;
  model: string;
  base_url: string | null;
  api_key_masked: string | null;
  configured: boolean;
  source: "database" | null;
  validation_status: "未验证" | "已验证" | "验证失败";
  validation_message: string | null;
  last_tested_at: string | null;
  supports_tools: boolean | null;
  supports_json: boolean | null;
  supports_streaming: boolean | null;
  supports_vision: boolean | null;
  capability_checked_at: string | null;
  is_default: boolean;
}

export interface ProviderConfigInput {
  api_key?: string | null;
  model: string;
  base_url?: string | null;
}

export interface ProviderTestResult {
  provider: string;
  ok: boolean;
  message: string;
  latency_ms: number | null;
}

export interface ProviderModelsResult {
  provider: string;
  models: string[];
  message: string | null;
}

export interface PipelineBucket {
  status: ApplicationStatus;
  count: number;
}

export interface Dashboard {
  pipeline: PipelineBucket[];
  attention: TimelineNode[];
  today_actions: {
    items: DashboardAction[];
    total: number;
    pending_count: number;
  };
}

export interface DashboardAction {
  task_id: number;
  planner_session_id: number;
  application_id: number;
  company_name: string;
  position_title: string;
  title: string;
  detail: string | null;
  priority: number;
  status: "待处理" | "已完成" | "已跳过";
  estimated_minutes: number;
  scheduled_at: string | null;
  deferred_until: string | null;
  source_ids: string[];
}

export const APPLICATION_STATUSES = [
  "已投递",
  "测评",
  "笔试",
  "AI面",
  "一面",
  "二面",
  "三面",
  "HR面",
  "offer",
  "挂",
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface CompanySummary {
  id: number;
  name: string;
}

export interface PositionSummary {
  id: number;
  title: string;
  jd_text: string | null;
  company: CompanySummary;
}

export interface Application {
  id: number;
  position_id: number;
  status: ApplicationStatus;
  applied_at: string | null;
  note: string | null;
  created_at: string;
  position: PositionSummary;
}

export interface ApplicationInput {
  company_name: string;
  position_title: string;
  jd_text: string | null;
  status: ApplicationStatus;
  applied_at: string | null;
  note: string | null;
}

export const NODE_TYPES = [
  "网申截止",
  "测评",
  "笔试",
  "AI面",
  "一面",
  "二面",
  "三面",
  "HR面",
  "其他",
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

export const TIME_MODES = ["固定时间", "截止窗口"] as const;
export type TimeMode = (typeof TIME_MODES)[number];

export const NODE_STATUSES = ["待处理", "已完成", "已错过", "已取消"] as const;
export type NodeStatus = (typeof NODE_STATUSES)[number];

export type ParseSessionStatus =
  | "解析中"
  | "待确认"
  | "已确认"
  | "已丢弃"
  | "解析失败";

export interface NoticeExtraction {
  company_name: string | null;
  position_title: string | null;
  node_type: NodeType | null;
  time_mode: TimeMode | null;
  deadline_workdays: number | null;
  scheduled_at: string | null;
  ends_at: string | null;
  source: string | null;
}

export interface ParseSession {
  id: number;
  thread_id: string;
  raw_text: string;
  provider: string;
  extracted_payload: NoticeExtraction | null;
  confirmed_payload: Record<string, unknown> | null;
  status: ParseSessionStatus;
  timeline_node_id: number | null;
  error_message: string | null;
  created_at: string;
  resolved_at: string | null;
  recommended_applications: Application[];
}

export interface ParseConfirmation {
  application_id: number;
  node_type: NodeType;
  time_mode: TimeMode;
  scheduled_at: string;
  ends_at: string | null;
  source: string | null;
}

export type TimelineAlert = "冲突" | "临期" | "逾期";

export interface TimelineNode {
  id: number;
  application_id: number;
  application: Application;
  node_type: NodeType;
  scheduled_at: string | null;
  ends_at: string | null;
  time_mode: TimeMode;
  status: NodeStatus;
  source: string | null;
  title: string | null;
  detail: string | null;
  created_at: string;
  alert_types: TimelineAlert[];
  conflict_node_ids: number[];
}

export type IntelSessionStatus = "聚合中" | "待裁决" | "已完成" | "已丢弃" | "失败";
export type IntelRoundType = "测评" | "笔试" | "AI面" | "一面" | "二面" | "三面" | "HR面" | "多轮综合" | "未注明";
export interface InterviewIntel { id: number; application_id: number; title: string; round_type: IntelRoundType; provider: string; application: Application; payload: IntelPayload; confidence: number | null; sources: SourceRecord[]; created_at: string; }
export interface SourceRecord { id: string; title: string; url: string | null; text: string; kind: "manual" | "image" | "web" | "unknown"; file_name: string | null; }
export interface IntelProgress { stage: string; sources: Pick<SourceRecord, "id" | "title" | "url" | "kind" | "file_name">[]; found?: number; accepted?: number; rejected?: number; errors?: string[]; insight_error?: string; }
export interface IntelFact { value: string; source_ids: string[]; }
export interface IntelRound { round_type: string; duration_minutes: number | null; question_types: IntelFact[]; focus_topics: IntelFact[]; source_ids: string[]; }
export interface IntelQuestion { question: string; category: string; round_type: string; answer_outline: string; source_ids: string[]; }
export interface PreparationItem { title: string; detail: string; priority: number; source_ids: string[]; }
export interface IntelPayload { summary: IntelFact | null; rounds: IntelRound[]; questions: IntelQuestion[]; frequent_topics: IntelFact[]; difficulty: IntelFact | null; preparation_items: PreparationItem[]; conflicts: { field: string; candidates: IntelFact[] }[]; }
export interface IntelSession { id: number; thread_id: string; application_id: number; provider: string; round_type: IntelRoundType; user_paste: string | null; image_texts: { name: string; text: string }[]; supplement_web?: boolean; draft_payload: IntelPayload | null; conflicts: IntelPayload["conflicts"] | null; progress_payload: IntelProgress | null; status: IntelSessionStatus; interview_intel_id: number | null; error_message: string | null; queue_task_id?: string | null; created_at: string; resolved_at: string | null; }
export interface IntelDirection { title: string; source_ids: string[]; round_types: string[]; representative_questions: string[]; }
export interface IntelCoreQuestion { question: string; category: string; round_type: string; reason: string; source_ids: string[]; }
export interface IntelInsightPreparation { title: string; detail: string; priority: number; source_ids: string[]; }
export interface IntelInsight { status: "未生成" | "生成中" | "已生成" | "失败" | "暂无资料"; high_frequency_directions: IntelDirection[]; core_questions: IntelCoreQuestion[]; preparation_items: IntelInsightPreparation[]; error_message: string | null; }
export interface IntelDossier { application_id: number; position_id: number; company_name: string; position_title: string; payload: IntelPayload; insight: IntelInsight; materials: InterviewIntel[]; sources: SourceRecord[]; reminder: { id: number; scheduled_at: string | null; title: string | null } | null; }
export interface IntelChatSource { id: string; title: string; url: string | null; kind: string; file_name: string | null; published_at: string | null; }
export interface IntelChatMessage { id: number; role: "user" | "assistant"; content: string; status: "生成中" | "已完成" | "失败"; source_ids: string[]; agent_stage?: string | null; degraded?: boolean; insufficient_data?: boolean; used_tools?: string[]; answer_mode?: "sourced" | "mixed" | "general" | null; search_status?: "not_used" | "success" | "empty" | "failed" | null; sources?: IntelChatSource[]; created_at: string; }

export interface AvailabilityWindow { weekday: number; start: string; end: string; }
export interface ResumeProfile { resume_text: string; file_name: string | null; updated_at: string; }
export interface PlannerGap { name: string; evidence: string; }
export interface PlannerAction { title: string; detail: string | null; gap?: string | null; priority: number; estimated_minutes?: number; source_ids: string[]; evidence?: { kind: "resume" | "jd" | "intel" | "timeline"; reference: string }[]; }
export interface PlannerReport { summary: string | null; strengths: PlannerGap[]; gaps: PlannerGap[]; actions: PlannerAction[]; }
export interface ScheduledTask { title: string; detail: string | null; gap: string; source_ids: string[]; estimated_minutes: number; scheduled_at: string; ends_at: string; }
export interface PlannerSession { id: number; application_id: number; application: Application; provider: string; available_windows: AvailabilityWindow[]; draft_payload: PlannerReport | { gaps: PlannerGap[]; tasks: ScheduledTask[] } | null; status: "生成中" | "待确认" | "已确认" | "已完成" | "已丢弃" | "失败"; error_message: string | null; queue_task_id?: string | null; created_at: string; resolved_at: string | null; }
export interface PreparationTask { id: number; planner_session_id: number; application_id: number; title: string; detail: string | null; gap: string | null; source_ids: string[]; evidence?: { kind: "resume" | "jd" | "intel" | "timeline"; reference: string }[]; scheduled_at: string | null; ends_at: string | null; estimated_minutes: number; priority: number; action_index: number | null; deferred_until: string | null; status: "待处理" | "已完成" | "已跳过"; timeline_node_id: number | null; created_at: string; }
export interface DailyBriefing { id: number; briefing_date: string; payload: { alerts: { timeline_node_id: number; title: string; scheduled_at: string; alert_types: TimelineAlert[] }[]; today_tasks: { task_id: number; title: string; scheduled_at: string; ends_at: string; application_id: number }[]; new_sources: { application_id: number; title: string; url: string }[]; search_errors: { application_id: number; message: string }[]; }; created_at: string; }
