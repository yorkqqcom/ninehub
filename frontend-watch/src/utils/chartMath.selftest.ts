/**
 * Lightweight checks for chartMath (run: npx --yes tsx src/utils/chartMath.selftest.ts)
 */
import {
  amountVwapLooksValid,
  cumulativeAvg,
  isConceptIndexSymbol,
  toSessionPoints,
  type ChartBar,
} from "./chartMath";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

assert(isConceptIndexSymbol("880214"), "880214 is concept");
assert(isConceptIndexSymbol("880214.TDX"), "880214.TDX is concept");
assert(!isConceptIndexSymbol("000557.SZ"), "stock is not concept");

const stockBars: ChartBar[] = [
  { ts: "2026-07-20T09:31:00", close: 3.7, volume: 1000, amount: 3690 },
  { ts: "2026-07-20T09:32:00", close: 3.72, volume: 1000, amount: 3713 },
  { ts: "2026-07-20T09:33:00", close: 3.73, volume: 1000, amount: 3717 },
];

const conceptBars: ChartBar[] = [
  { ts: "2026-07-20T09:31:00", close: 895.08, volume: 3226902, amount: 322691360 },
  { ts: "2026-07-20T09:32:00", close: 904.13, volume: 2002674, amount: 200268432 },
  { ts: "2026-07-20T09:33:00", close: 901.57, volume: 1294221, amount: 129423072 },
];

const stockPts = toSessionPoints(stockBars);
const conceptPts = toSessionPoints(conceptBars);

assert(amountVwapLooksValid(stockPts), "stock amount/vol should look like price");
assert(!amountVwapLooksValid(conceptPts), "concept amount/vol≈100 must be rejected");

const stockAvg = cumulativeAvg(stockPts);
const conceptAvg = cumulativeAvg(conceptPts);

assert(Math.abs(stockAvg[0]! - 3.69) < 0.02, `stock avg0=${stockAvg[0]}`);
assert(conceptAvg[0]! > 800 && conceptAvg[0]! < 1000, `concept avg0=${conceptAvg[0]} (must track index)`);
assert(conceptAvg[2]! > 800 && conceptAvg[2]! < 1000, `concept avg2=${conceptAvg[2]}`);

const noisy = toSessionPoints([
  ...conceptBars,
  { ts: "2026-07-20T09:34:00", close: 901.0, volume: 5.8e-39, amount: 5.8e-39 },
]);
assert(noisy[noisy.length - 1]!.volume === 0, "noise volume sanitized");

console.log("chartMath.selftest ok");
