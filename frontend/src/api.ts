import type {
  Application,
  ApplicationInput,
  ApplicationStatus,
  Company,
  CompanyInput,
  Page,
  Position,
  PositionInput,
} from "./types";

type QueryValue = string | number | undefined;

function queryString(params: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const value = query.toString();
  return value ? `?${value}` : "";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).filter(Boolean).join("；")
      : detail;
    throw new Error(message || `请求失败（${response.status}）`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  companies: {
    list: (params: { page?: number; page_size?: number; q?: string } = {}) =>
      request<Page<Company>>(`/api/companies${queryString(params)}`),
    get: (id: number) => request<Company>(`/api/companies/${id}`),
    create: (input: CompanyInput) =>
      request<Company>("/api/companies", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    update: (id: number, input: Partial<CompanyInput>) =>
      request<Company>(`/api/companies/${id}`, {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    remove: (id: number) =>
      request<void>(`/api/companies/${id}`, { method: "DELETE" }),
  },
  positions: {
    list: (
      params: {
        page?: number;
        page_size?: number;
        q?: string;
        company_id?: number;
      } = {},
    ) => request<Page<Position>>(`/api/positions${queryString(params)}`),
    get: (id: number) => request<Position>(`/api/positions/${id}`),
    create: (input: PositionInput) =>
      request<Position>("/api/positions", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    update: (id: number, input: Partial<PositionInput>) =>
      request<Position>(`/api/positions/${id}`, {
        method: "PATCH",
        body: JSON.stringify(input),
      }),
    remove: (id: number) =>
      request<void>(`/api/positions/${id}`, { method: "DELETE" }),
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
    update: (id: number, input: Partial<Omit<ApplicationInput, "status">>) =>
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
};
