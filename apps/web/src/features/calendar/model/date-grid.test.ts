import { describe, expect, it } from "vitest";

import {
  getCalendarDateKey,
  getCalendarMonthDays,
  getCalendarWeekDays,
  getDashboardCalendarDays,
} from "./date-grid";

function dateParts(date: Date) {
  return [date.getFullYear(), date.getMonth(), date.getDate()];
}

describe("calendar date grids", () => {
  it("keeps the original 28, 35, and 42-cell month grids", () => {
    expect(getCalendarMonthDays(new Date(2021, 1, 1))).toHaveLength(28);
    expect(getCalendarMonthDays(new Date(2025, 8, 1))).toHaveLength(35);
    expect(getCalendarMonthDays(new Date(2025, 5, 1))).toHaveLength(42);
  });

  it("starts month grids on Monday and does not mutate the input", () => {
    const month = new Date(2025, 5, 18, 14, 30);
    const originalTime = month.getTime();
    const days = getCalendarMonthDays(month);

    expect(dateParts(days[0])).toEqual([2025, 4, 26]);
    expect(days[0].getDay()).toBe(1);
    expect(dateParts(days.at(-1)!)).toEqual([2025, 6, 6]);
    expect(month.getTime()).toBe(originalTime);
  });

  it("extends only the dashboard grid to six weeks", () => {
    const days = getDashboardCalendarDays(new Date(2021, 1, 1));

    expect(days).toHaveLength(42);
    expect(dateParts(days[0])).toEqual([2021, 1, 1]);
    expect(dateParts(days.at(-1)!)).toEqual([2021, 2, 14]);
  });

  it("builds a Monday-to-Sunday week at local midnight", () => {
    const source = new Date(2026, 7, 20, 16, 45);
    const originalTime = source.getTime();
    const days = getCalendarWeekDays(source);

    expect(days.map((day) => day.getDay())).toEqual([1, 2, 3, 4, 5, 6, 0]);
    expect(days.every((day) => day.getHours() === 0)).toBe(true);
    expect(dateParts(days[0])).toEqual([2026, 7, 17]);
    expect(dateParts(days[6])).toEqual([2026, 7, 23]);
    expect(source.getTime()).toBe(originalTime);
  });

  it("formats date keys from local calendar fields", () => {
    expect(getCalendarDateKey(new Date(2026, 0, 5, 23, 30))).toBe(
      "2026-01-05",
    );
  });
});
