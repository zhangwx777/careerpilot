import type {
  Application,
  ApplicationInput,
  ApplicationStatus,
  Dashboard,
  Page,
  ParseConfirmation,
  ParseSession,
  ParseSessionStatus,
  NodeStatus,
  TimelineNode,
  AvailabilityWindow,
  DailyBriefing,
  PlannerSession,
  PreparationTask,
  ProviderOption,
  ProviderConfigInput,
  ProviderTestResult,
  ProviderModelsResult,
  ResumeProfile,
  ScheduledTask,
} from "./types";

type QueryValue = string | number | undefined;

export type ApiErrorKind = "config" | "auth" | "timeout" | "format" | "network" | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;

  constructor(message: string, status: number, kind: ApiErrorKind) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind;
  }
}

function classifyError(status: number, message: string): ApiErrorKind {
  const normalized = message.toLowerCase();
  if (status === 401 || status === 403 || /认证|鉴权|unauthori|forbidden/.test(normalized)) return "auth";
  if (/超时|timeout|timed out/.test(normalized)) return "timeout";
  if (/格式|json|结构化|schema|未识别|返回异常/.test(normalized)) return "format";
  if (/配置|api key|base url|模型.*配置|暂无可用/.test(normalized)) return "config";
  if (status === 0 || /网络|network|连接失败/.test(normalized)) return "network";
  return "unknown";
}

function redactSecrets(message: string): string {
  return message
    .replace(/\bsk-[A-Za-z0-9_-]{16,}\b/g, "[API key]")
    .replace(/\b(key|token)[=:][^\s,;]+/gi, "$1=[已隐藏]");
}

function queryString(params: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const value = query.toString();
  return value ? `?${value}` : "";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: options?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new ApiError("无法连接后端服务，请确认服务已启动。", 0, "network");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).filter(Boolean).join("；")
      : detail;
    const safeMessage = redactSecrets(message || (response.status >= 500 ? "服务暂时不可用，请稍后重试。" : `请求未完成（${response.status}）`));
    throw new ApiError(safeMessage, response.status, classifyError(response.status, safeMessage));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: {
    get: () => request<Dashboard>("/api/dashboard"),
  },
  providers: {
    list: () => request<ProviderOption[]>("/api/providers"),
    save: (provider: string, input: ProviderConfigInput) =>
      request<ProviderOption>(`/api/llm/providers/${provider}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    remove: (provider: string) =>
      request<ProviderOption[]>(`/api/llm/providers/${provider}`, { method: "DELETE" }),
    test: async (provider: string, input: ProviderConfigInput) => {
      const result = await request<ProviderTestResult>(`/api/llm/providers/${provider}/test`, {
        method: "POST",
        body: JSON.stringify(input),
      });
      return { ...result, message: redactSecrets(result.message) };
    },
    models: (provider: string, input: { api_key?: string; model?: string; base_url?: string | null } = {}) =>
      request<ProviderModelsResult>(`/api/llm/providers/${provider}/models`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    setDefault: (provider: string | null) =>
      request<ProviderOption[]>("/api/llm/default", {
        method: "PUT",
        body: JSON.stringify({ provider }),
      }),
  },
  applications: {
    list: (
      params: {
        page?: number;
        page_size?: number;
        q?: string;
        status?: ApplicationStatus;
        company_id?: number;
        position_id?: number;
      } = {},
    ) => request<Page<Application>>(`/api/applications${queryString(params)}`),
    get: (id: number) => request<Application>(`/api/applications/${id}`),
    create: (input: ApplicationInput) =>
      request<Application>("/api/applications", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    update: (id: number, input: Partial<ApplicationInput>) =>
      request<Application>(`/api/applications/${id}`, {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    transition: (id: number, status: ApplicationStatus) =>
      request<Application>(`/api/applications/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    remove: (id: number) =>
      request<void>(`/api/applications/${id}`, { method: "DELETE" }),
  },
  parseSessions: {
    list: (
      params: {
        page?: number;
        page_size?: number;
        status?: ParseSessionStatus;
      } = {},
    ) => request<Page<ParseSession>>(`/api/parse-sessions${queryString(params)}`),
    get: (id: number) => request<ParseSession>(`/api/parse-sessions/${id}`),
    create: (rawText: string, provider?: string) =>
      request<ParseSession>("/api/parse-sessions", {
        method: "POST",
        body: JSON.stringify({ raw_text: rawText, provider }),
      }),
    createApplication: (id: number, input: { company_name: string; position_title: string }) =>
      request<Application>(`/api/parse-sessions/${id}/application`, {
        method: "POST",
        body: JSON.stringify(input),
      }),
    confirm: (id: number, confirmation: ParseConfirmation) =>
      request<ParseSession>(`/api/parse-sessions/${id}/confirm`, {
        method: "POST",
        body: JSON.stringify(confirmation),
      }),
    discard: (id: number) =>
      request<ParseSession>(`/api/parse-sessions/${id}/discard`, {
        method: "POST",
      }),
  },
  timeline: {
    list: (
      params: {
        page?: number;
        page_size?: number;
        start?: string;
        end?: string;
        status?: NodeStatus;
      } = {},
    ) => request<Page<TimelineNode>>(`/api/timeline${queryString(params)}`),
    transition: (id: number, status: NodeStatus) =>
      request<TimelineNode>(`/api/timeline/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
  },
  intel: {
    create: (input: { application_id: number; provider?: string; round_type: import("./types").IntelRoundType; user_paste: string | null; image_texts: { name: string; text: string }[]; supplement_web: boolean }) => request<import("./types").IntelSession>("/api/intel", { method: "POST", body: JSON.stringify(input) }),
    list: (params: { page?: number; page_size?: number; application_id?: number; q?: string } = {}) => request<Page<import("./types").InterviewIntel>>(`/api/intel${queryString(params)}`),
    sessions: () => request<import("./types").IntelSession[]>("/api/intel-sessions"),
    session: (id: number) => request<import("./types").IntelSession>(`/api/intel-sessions/${id}`),
    resolve: (id: number, resolutions: Record<string, string>) => request<import("./types").IntelSession>(`/api/intel-sessions/${id}/resolve`, { method: "POST", body: JSON.stringify({ resolutions }) }),
    discard: (id: number) => request<import("./types").IntelSession>(`/api/intel-sessions/${id}/discard`, { method: "POST" }),
    extractImages: (input: { provider?: string; images: { name: string; mime_type: string; data_url: string }[] }) => request<{ images: { name: string; text: string }[]; combined_text: string }>("/api/intel/images/extract", { method: "POST", body: JSON.stringify(input) }),
    dossier: (application_id: number) => request<import("./types").IntelDossier>(`/api/intel/dossier${queryString({ application_id })}`),
    rebuildDossier: (input: { application_id: number; provider?: string }) => request<import("./types").IntelDossier>("/api/intel/dossier/rebuild", { method: "POST", body: JSON.stringify(input) }),
    deleteMaterial: (id: number) => request<{ deleted: number }>(`/api/intel/materials/${id}`, { method: "DELETE" }),
    chat: (input: { application_id: number; provider?: string; question: string }) => request<{ message: import("./types").IntelChatMessage; source_ids: string[] }>("/api/intel/chat", { method: "POST", body: JSON.stringify(input) }),
    chatHistory: (application_id: number) => request<import("./types").IntelChatMessage[]>(`/api/intel/chat${queryString({ application_id })}`),
  },
  planner: {
    resume: () => request<ResumeProfile>("/api/resume-profile"),
    uploadResume: (file: File) => { const body = new FormData(); body.append("file", file); return request<ResumeProfile>("/api/resume-profile/upload", { method: "POST", body }); },
    saveResume: (resume_text: string) => request<ResumeProfile>("/api/resume-profile", { method: "PUT", body: JSON.stringify({ resume_text }) }),
    create: (input: { application_id: number; provider?: string }) => request<PlannerSession>("/api/planner-sessions", { method: "POST", body: JSON.stringify(input) }),
    sessions: () => request<PlannerSession[]>("/api/planner-sessions"),
    session: (id: number) => request<PlannerSession>(`/api/planner-sessions/${id}`),
    confirm: (id: number, tasks: ScheduledTask[]) => request<PlannerSession>(`/api/planner-sessions/${id}/confirm`, { method: "POST", body: JSON.stringify({ tasks }) }),
    discard: (id: number) => request<PlannerSession>(`/api/planner-sessions/${id}/discard`, { method: "POST" }),
    tasks: (params: { page?: number; page_size?: number; application_id?: number; status?: PreparationTask["status"] } = {}) => request<Page<PreparationTask>>(`/api/preparation-tasks${queryString(params)}`),
    updateTask: (id: number, status: PreparationTask["status"]) => request<PreparationTask>(`/api/preparation-tasks/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
  },
  briefings: {
    run: () => request<DailyBriefing>("/api/daily-briefings/run", { method: "POST" }),
    list: (params: { page?: number; page_size?: number } = {}) => request<Page<DailyBriefing>>(`/api/daily-briefings${queryString(params)}`),
    get: (id: number) => request<DailyBriefing>(`/api/daily-briefings/${id}`),
  },
};
