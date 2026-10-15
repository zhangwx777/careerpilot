import type { DashboardFeedItem } from "./types";

export function compareDashboardFeed(left: DashboardFeedItem, right: DashboardFeedItem): number {
  const leftAttention = left.kind === "timeline" && left.alert_types.length > 0;
  const rightAttention = right.kind === "timeline" && right.alert_types.length > 0;
  if (leftAttention !== rightAttention) return leftAttention ? -1 : 1;
  const leftTime = left.scheduled_at ? Date.parse(left.scheduled_at) : Number.POSITIVE_INFINITY;
  const rightTime = right.scheduled_at ? Date.parse(right.scheduled_at) : Number.POSITIVE_INFINITY;
  const safeLeftTime = Number.isNaN(leftTime) ? Number.POSITIVE_INFINITY : leftTime;
  const safeRightTime = Number.isNaN(rightTime) ? Number.POSITIVE_INFINITY : rightTime;
  if (safeLeftTime !== safeRightTime) return safeLeftTime < safeRightTime ? -1 : 1;
  if (left.kind === "preparation" && right.kind === "preparation") {
    return (left.priority ?? 3) - (right.priority ?? 3);
  }
  if (left.kind === right.kind) return 0;
  return left.kind === "timeline" ? -1 : 1;
}
