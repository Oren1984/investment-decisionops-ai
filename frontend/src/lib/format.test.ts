import { describe, expect, it } from "vitest";
import { dayDifference, fmtClock, fmtDuration, fmtMoney, fmtPct, utcOffsetLabel, ymd } from "./format";

// Controlled instants (plan §17.3): the clock strip's date difference and offsets must follow IANA rules.
describe("time formatting across zones", () => {
  it("shows a +1 day difference for Tokyo late on a Jerusalem evening", () => {
    const t = new Date("2026-10-19T20:30:00Z"); // 23:30 Jerusalem (UTC+3), 05:30 next day Tokyo
    expect(ymd(t, "Asia/Jerusalem")).toBe("2026-10-19");
    expect(ymd(t, "Asia/Tokyo")).toBe("2026-10-20");
    expect(dayDifference(t, "Asia/Jerusalem", "Asia/Tokyo")).toBe(1);
  });

  it("shows -1 for New York at Jerusalem 01:30 on Monday", () => {
    const t = new Date("2026-10-18T22:30:00Z"); // Mon 01:30 Jerusalem, Sun 18:30 New York
    expect(dayDifference(t, "Asia/Jerusalem", "America/New_York")).toBe(-1);
    expect(fmtClock(t, "Asia/Jerusalem", false)).toBe("01:30");
  });

  it("tracks the US/EU DST mismatch window and the Israel DST start", () => {
    const mismatch = new Date("2026-03-20T12:00:00Z");
    expect(utcOffsetLabel(mismatch, "America/New_York")).toBe("UTC-4");
    expect(utcOffsetLabel(mismatch, "Europe/London")).toMatch(/^UTC(\+0)?$/); // ICU builds differ for zero
    expect(utcOffsetLabel(new Date("2026-03-26T12:00:00Z"), "Asia/Jerusalem")).toBe("UTC+2");
    expect(utcOffsetLabel(new Date("2026-03-28T12:00:00Z"), "Asia/Jerusalem")).toBe("UTC+3");
  });

  it("formats countdowns, including multi-day ones and negative input", () => {
    expect(fmtDuration(3725)).toBe("01:02:05");
    expect(fmtDuration(2 * 86400 + 61)).toBe("2d 00:01:01");
    expect(fmtDuration(-5)).toBe("00:00:00");
  });
});

describe("number formatting", () => {
  it("never invents values for missing data", () => {
    expect(fmtMoney(null, "ILS")).toBe("—");
    expect(fmtPct(Number.NaN)).toBe("—");
    expect(fmtMoney(1234567.891, "ILS", 2)).toBe("1,234,567.89 ILS");
    expect(fmtPct(1.5)).toBe("+1.50%");
  });
});
