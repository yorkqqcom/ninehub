/** A-share chart geometry & quote helpers (pure functions). */

export type ChartBar = {
  ts?: string | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
  amount?: number | null;
};

const DAY_RE = /^\d{4}-\d{2}-\d{2}/;

export function dayKey(ts: string | null | undefined): string | null {
  if (!ts) return null;
  const s = String(ts).slice(0, 10);
  return DAY_RE.test(s) ? s : null;
}

/** TDX concept / sector index bare code 880xxx (optional .TDX). */
export function isConceptIndexSymbol(raw: string | null | undefined): boolean {
  let text = String(raw || "").trim().toUpperCase();
  if (text.endsWith(".TDX")) text = text.slice(0, -4);
  return /^880\d{3}$/.test(text);
}

export function mmDd(isoDay: string): string {
  return isoDay.slice(5);
}

/** Minutes from HH:MM in ts; null if unparsable. */
function hmMinutes(ts: string): { h: number; m: number } | null {
  const m = String(ts).match(/T(\d{2}):(\d{2})/);
  if (!m) return null;
  return { h: Number(m[1]), m: Number(m[2]) };
}

/**
 * A-share continuous session slot 0..239.
 * Morning 09:30–11:30 → 0..119 (11:30 → 119);
 * Afternoon 13:00–15:00 → 120..239 (15:00 → 239).
 */
export function mapIntradaySlot(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const hm = hmMinutes(ts);
  if (!hm) return null;
  const mins = hm.h * 60 + hm.m;
  const amStart = 9 * 60 + 30;
  const amEnd = 11 * 60 + 30;
  const pmStart = 13 * 60;
  const pmEnd = 15 * 60;
  if (mins >= amStart && mins <= amEnd) {
    return Math.min(119, Math.max(0, mins - amStart));
  }
  if (mins >= pmStart && mins <= pmEnd) {
    return 120 + Math.min(119, Math.max(0, mins - pmStart));
  }
  return null;
}

export type SlotPoint = {
  slot: number;
  bar: ChartBar;
  close: number;
  volume: number;
  amount: number;
};

/** Collapse to one bar per slot (last wins), sorted by slot. */
export function toSessionPoints(bars: ChartBar[]): SlotPoint[] {
  const map = new Map<number, SlotPoint>();
  for (const bar of bars) {
    const slot = mapIntradaySlot(bar.ts);
    if (slot === null) continue;
    const close = Number(bar.close);
    if (!Number.isFinite(close) || close <= 0) continue;
    map.set(slot, {
      slot,
      bar,
      close,
      volume: sanitizeQty(Number(bar.volume)),
      amount: sanitizeQty(Number(bar.amount)),
    });
  }
  return [...map.values()].sort((a, b) => a.slot - b.slot);
}

/** Drop float noise / non-positive quantities from TDX bars. */
export function sanitizeQty(v: number): number {
  return Number.isFinite(v) && v > 1e-6 ? v : 0;
}

/**
 * True when amount/volume looks like a price-scale VWAP (stocks).
 * TDX concept/index bars often keep amount≈vol*100, which is NOT yuan price —
 * using it places the 均价 line near 100 while index is ~900+.
 */
export function amountVwapLooksValid(points: SlotPoint[]): boolean {
  let samples = 0;
  let ok = 0;
  for (const p of points) {
    if (p.amount <= 0 || p.volume <= 0 || p.close <= 0) continue;
    samples += 1;
    const px = p.amount / p.volume;
    if (px >= p.close * 0.4 && px <= p.close * 2.5) ok += 1;
    if (samples >= 12) break;
  }
  return samples > 0 && ok / samples >= 0.6;
}

/**
 * Cumulative session average (分时均价).
 * Prefer amount/vol when valid; else volume-weighted close; else simple close mean.
 */
export function cumulativeAvg(points: SlotPoint[]): number[] {
  const useAmount = amountVwapLooksValid(points);
  let sumAmt = 0;
  let sumVolAmt = 0;
  let sumCv = 0;
  let sumVolCv = 0;
  let sumC = 0;
  let n = 0;
  const out: number[] = [];
  for (const p of points) {
    n += 1;
    sumC += p.close;
    if (p.volume > 0) {
      sumCv += p.close * p.volume;
      sumVolCv += p.volume;
    }
    if (useAmount && p.amount > 0 && p.volume > 0) {
      sumAmt += p.amount;
      sumVolAmt += p.volume;
    }
    if (useAmount && sumVolAmt > 0) {
      out.push(sumAmt / sumVolAmt);
    } else if (sumVolCv > 0) {
      out.push(sumCv / sumVolCv);
    } else {
      out.push(sumC / n);
    }
  }
  return out;
}

export function sma(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    if (i + 1 >= window) out.push(sum / window);
    else out.push(null);
  }
  return out;
}

export type QuoteStats = {
  last: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  change: number | null;
  changePct: number | null;
  dir: "rise" | "fall" | "flat";
  lastText: string;
  changeText: string;
  pctText: string;
  openText: string;
  highText: string;
  lowText: string;
  closeText: string;
};

function fmtPrice(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

export function quoteStatsIntraday(
  bars: ChartBar[],
  prevClose: number | null,
): QuoteStats {
  const closes = bars.map((b) => Number(b.close)).filter((v) => Number.isFinite(v) && v > 0);
  const opens = bars.map((b) => Number(b.open)).filter((v) => Number.isFinite(v) && v > 0);
  const highs = bars.map((b) => Number(b.high)).filter((v) => Number.isFinite(v) && v > 0);
  const lows = bars.map((b) => Number(b.low)).filter((v) => Number.isFinite(v) && v > 0);
  const last = closes.length ? closes[closes.length - 1] : null;
  const open = opens.length ? opens[0] : null;
  const high = highs.length ? Math.max(...highs) : null;
  const low = lows.length ? Math.min(...lows) : null;
  const close = last;
  let change: number | null = null;
  let changePct: number | null = null;
  let dir: "rise" | "fall" | "flat" = "flat";
  if (last !== null && prevClose !== null && prevClose > 0) {
    change = last - prevClose;
    changePct = (change / prevClose) * 100;
    dir = change > 0 ? "rise" : change < 0 ? "fall" : "flat";
  }
  return {
    last,
    open,
    high,
    low,
    close,
    change,
    changePct,
    dir,
    lastText: fmtPrice(last),
    changeText:
      change === null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}`,
    pctText:
      changePct === null
        ? "—"
        : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`,
    openText: fmtPrice(open),
    highText: fmtPrice(high),
    lowText: fmtPrice(low),
    closeText: fmtPrice(close),
  };
}

export function quoteStatsDaily(bars: ChartBar[]): QuoteStats {
  if (!bars.length) {
    return quoteStatsIntraday([], null);
  }
  const last = bars[bars.length - 1];
  const prev = bars.length >= 2 ? bars[bars.length - 2] : null;
  const lastC = Number(last.close);
  const prevC = prev ? Number(prev.close) : null;
  const open = Number(last.open);
  const high = Number(last.high);
  const low = Number(last.low);
  const close = Number.isFinite(lastC) && lastC > 0 ? lastC : null;
  let change: number | null = null;
  let changePct: number | null = null;
  let dir: "rise" | "fall" | "flat" = "flat";
  if (close !== null && prevC !== null && Number.isFinite(prevC) && prevC > 0) {
    change = close - prevC;
    changePct = (change / prevC) * 100;
    dir = change > 0 ? "rise" : change < 0 ? "fall" : "flat";
  }
  return {
    last: close,
    open: Number.isFinite(open) && open > 0 ? open : null,
    high: Number.isFinite(high) && high > 0 ? high : null,
    low: Number.isFinite(low) && low > 0 ? low : null,
    close,
    change,
    changePct,
    dir,
    lastText: fmtPrice(close),
    changeText:
      change === null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}`,
    pctText:
      changePct === null
        ? "—"
        : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`,
    openText: fmtPrice(Number.isFinite(open) && open > 0 ? open : null),
    highText: fmtPrice(Number.isFinite(high) && high > 0 ? high : null),
    lowText: fmtPrice(Number.isFinite(low) && low > 0 ? low : null),
    closeText: fmtPrice(close),
  };
}

export function cropLastSession(rows: ChartBar[]): ChartBar[] {
  let maxDay: string | null = null;
  for (const b of rows) {
    const d = dayKey(b.ts);
    if (d && (maxDay === null || d > maxDay)) maxDay = d;
  }
  if (!maxDay) {
    return [...rows].sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
  }
  return rows
    .filter((b) => dayKey(b.ts) === maxDay)
    .sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
}

export function formatSessionLabel(rows: ChartBar[]): string {
  if (!rows.length) return "分时";
  const d = dayKey(rows[0]?.ts) || dayKey(rows[rows.length - 1]?.ts);
  return d ? `${mmDd(d)} 分时` : "分时";
}

export function formatDailyRange(rows: ChartBar[]): string {
  if (!rows.length) return "日K";
  const first = dayKey(rows[0]?.ts);
  const last = dayKey(rows[rows.length - 1]?.ts);
  if (first && last) {
    if (first === last) return mmDd(first);
    return `${mmDd(first)} ~ ${mmDd(last)}`;
  }
  return "日K";
}
