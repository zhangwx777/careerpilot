export function formatDate(value: string | null): string {
  if (!value) return "未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function formatDateTime(value: string | null): string {
  if (!value) return "时间待补充";
  const date = new Date(value);
  const dateTimeParts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: string) => dateTimeParts.find((item) => item.type === type)?.value ?? "";
  return part("month") + "月" + part("day") + "日 " + part("weekday") + " " + part("hour") + ":" + part("minute");
}

export function toShanghaiInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return part("year") + "-" + part("month") + "-" + part("day") + "T" + part("hour") + ":" + part("minute");
}

export function toApiDate(value: string): string | null {
  if (!value) return null;
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : value + "+08:00").toISOString();
}
