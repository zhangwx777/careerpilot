export function dateKey(date: Date) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(date);
}

export function calendarDayKey(date: Date) {
  return date.getUTCFullYear() + "-" + String(date.getUTCMonth() + 1).padStart(2, "0") + "-" + String(date.getUTCDate()).padStart(2, "0");
}

export function calendarMonthForDateKey(value: string) {
  const [year, month] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, 1));
}

export function monthGrid(month: Date) {
  const first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
  const mondayOffset = (first.getUTCDay() + 6) % 7;
  const start = new Date(first);
  start.setUTCDate(first.getUTCDate() - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(start);
    date.setUTCDate(start.getUTCDate() + index);
    return date;
  });
}
