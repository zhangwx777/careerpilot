function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function deadlineAfterWorkdays(start: string, workdays: number): string {
  const [year, month, day] = start.slice(0, 10).split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  let remaining = workdays;
  // 仅跳过周末；法定节假日和调休日期由用户按原通知核对。
  while (remaining > 0) {
    date.setUTCDate(date.getUTCDate() + 1);
    if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) remaining -= 1;
  }
  return date.getUTCFullYear() + "-" + pad(date.getUTCMonth() + 1) + "-" + pad(date.getUTCDate()) + "T23:59";
}
