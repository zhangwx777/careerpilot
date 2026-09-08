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
