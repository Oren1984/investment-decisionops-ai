/** Formatting helpers. Instants come from the server in UTC (ISO 8601); display uses Intl with IANA zones. */

export function fmtMoney(value: number | null | undefined, currency?: string, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const n = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  return currency ? `${n} ${currency}` : n;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

export function fmtPct(value: number | null | undefined, digits = 2, signed = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = fmtNum(value, digits);
  return `${signed && value > 0 ? "+" : ""}${s}%`;
}

export function fmtTime(iso: string | Date | null | undefined, timeZone?: string, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, ...opts,
  }).format(d);
}

export function fmtDate(iso: string | Date | null | undefined, timeZone?: string): string {
  return fmtTime(iso, timeZone, { hour: undefined, minute: undefined, year: "numeric" });
}

export function fmtClock(d: Date, timeZone: string, seconds = true): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone, hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined, hour12: false,
  }).format(d);
}

export function fmtDay(d: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, weekday: "short", day: "2-digit", month: "short" }).format(d);
}

export function utcOffsetLabel(d: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "shortOffset" }).formatToParts(d);
  const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "UTC";
  return name.replace("GMT", "UTC");
}

/** Calendar date (YYYY-MM-DD) of an instant in a zone. */
export function ymd(d: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

export function dayDifference(d: Date, homeZone: string, otherZone: string): number {
  const a = Date.parse(ymd(d, homeZone));
  const b = Date.parse(ymd(d, otherZone));
  return Math.round((b - a) / 86_400_000);
}

export function fmtDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return days > 0 ? `${days}d ${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(h)}:${pad(m)}:${pad(sec)}`;
}

export function fmtAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
