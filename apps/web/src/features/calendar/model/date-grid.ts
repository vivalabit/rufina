export function getCalendarDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function getCalendarMonthDays(month: Date) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(
    month.getFullYear(),
    month.getMonth() + 1,
    0,
  ).getDate();
  const cellCount = Math.ceil((mondayOffset + daysInMonth) / 7) * 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);

  return Array.from({ length: cellCount }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return date;
  });
}

export function getDashboardCalendarDays(month: Date) {
  const days = getCalendarMonthDays(month);
  if (days.length === 42) return days;

  const lastDay = days[days.length - 1];
  return [
    ...days,
    ...Array.from({ length: 42 - days.length }, (_, index) => {
      const date = new Date(lastDay);
      date.setDate(lastDay.getDate() + index + 1);
      return date;
    }),
  ];
}

export function getCalendarWeekDays(date: Date) {
  const start = new Date(date);
  start.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  start.setHours(0, 0, 0, 0);

  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}
