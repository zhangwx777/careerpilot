import type { ApplicationStatus } from "../types";

const stages: ApplicationStatus[] = [
  "已投递",
  "测评",
  "笔试",
  "AI面",
  "一面",
  "二面",
  "三面",
  "HR面",
  "offer",
];

export function StatusRail({ status }: { status: ApplicationStatus }) {
  return (
    <div className="status-rail" aria-label={`投递阶段节点，当前状态：${status}`}>
      {stages.map((stage) => (
        <span key={stage} title={stage} aria-hidden="true" />
      ))}
    </div>
  );
}
