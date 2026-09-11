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
  const activeIndex = stages.indexOf(status);
  const failed = status === "挂";

  return (
    <div className={`status-rail ${failed ? "is-failed" : ""}`} aria-label={`当前状态：${status}`}>
      {stages.map((stage, index) => (
        <span
          key={stage}
          className={index <= activeIndex && !failed ? "is-reached" : ""}
          title={stage}
          aria-hidden="true"
        />
      ))}
      <strong className="status-label">{status}</strong>
    </div>
  );
}
