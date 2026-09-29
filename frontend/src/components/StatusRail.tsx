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
  const rejected = status === "挂";
  const currentIndex = stages.indexOf(status);
  return (
    <div
      className={rejected ? "status-rail is-rejected" : "status-rail"}
      aria-label={`投递阶段节点，当前状态：${status}`}
    >
      {stages.map((stage, index) => {
        const reached = !rejected && currentIndex >= 0 && index <= currentIndex;
        const current = !rejected && index === currentIndex;
        const className = [reached ? "is-reached" : "", current ? "is-current" : ""]
          .filter(Boolean)
          .join(" ");
        return (
          <span key={stage} className={className || undefined} title={stage} aria-hidden="true" />
        );
      })}
    </div>
  );
}
