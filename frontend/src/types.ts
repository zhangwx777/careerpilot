export const APPLICATION_STATUSES = [
  "已投递",
  "笔试",
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

export interface Company {
  id: number;
  name: string;
  industry: string | null;
  created_at: string;
}

export interface CompanySummary {
  id: number;
  name: string;
}

export interface Position {
  id: number;
  company_id: number;
  title: string;
  jd_text: string | null;
  created_at: string;
  company: CompanySummary;
}

export interface PositionSummary {
  id: number;
  title: string;
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

export interface CompanyInput {
  name: string;
  industry: string | null;
}

export interface PositionInput {
  company_id: number;
  title: string;
  jd_text: string | null;
}

export interface ApplicationInput {
  position_id: number;
  status: ApplicationStatus;
  applied_at: string | null;
  note: string | null;
}

export const NODE_TYPES = [
  "网申截止",
  "笔试",
  "一面",
  "二面",
  "三面",
  "HR面",
  "其他",
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

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
  status: NodeStatus;
  source: string | null;
  created_at: string;
  alert_types: TimelineAlert[];
  conflict_node_ids: number[];
}
