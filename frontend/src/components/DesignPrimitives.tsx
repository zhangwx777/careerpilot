import type { ReactNode } from "react";

type StatusTone = "ready" | "warning" | "danger" | "neutral";

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: StatusTone }) {
  return <span className={`status-badge status-badge-${tone}`}>{children}</span>;
}

export function ContextBar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`context-bar glass-surface ${className}`}>{children}</div>;
}
