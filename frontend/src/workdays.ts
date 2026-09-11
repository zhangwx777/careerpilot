function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function deadlineAfterWorkdays(start: string, workdays: number): string {
  const date = new Date(start);
  let remaining = workdays;
  // ponytail: 仅跳过周末；需要法定节假日时再接入节假日历。
  while (remaining > 0) {
    date.setDate(date.getDate() + 1);
    if (date.getDay() !== 0 && date.getDay() !== 6) remaining -= 1;
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T23:59`;
}
