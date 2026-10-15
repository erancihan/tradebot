// The equity chart: the "Hold the list" benchmark line is drawn only when
// the API sent one, each daily close lands on its nearest snapshot, and the
// snapshot labels and order pins are untouched.

import type { LineSeriesOption } from "echarts";

import { benchmarkOnSnapshots, equityOption, orderTraded } from "../src/charts/equityChart";
import type { EquitySeries } from "../src/types";
import { check } from "./harness";

const points = [
  { ts: "2026-10-01T14:30:00+00:00", equity: 10_000, cash: 0, mode: "paper" },
  { ts: "2026-10-01T19:30:00+00:00", equity: 10_100, cash: 0, mode: "paper" },
  { ts: "2026-10-02T15:00:00+00:00", equity: 10_200, cash: 0, mode: "paper" },
  { ts: "2026-10-05T19:45:00+00:00", equity: 10_300, cash: 0, mode: "paper" },
];
const order = { ts: "2026-10-01T19:31:00+00:00", symbol: "SPY", side: "buy", qty: 2, mode: "paper" };

const bare: EquitySeries = { mode: "paper", points };
const plain = equityOption(bare, [order]);
const plainSeries = plain.series as LineSeriesOption[];
check(plainSeries.length === 1, `no benchmark, one line: ${plainSeries.length}`);
check(plain.legend === undefined, "no legend for a single line");

const withBench: EquitySeries = {
  ...bare,
  benchmark: [
    { ts: "2026-10-01", value: 10_000 },
    { ts: "2026-10-02", value: 10_050 },
    { ts: "2026-10-05", value: 9_900 },
  ],
  benchmark_symbols: ["SPY", "QQQ"],
  benchmark_source: "cache",
};
const placed = benchmarkOnSnapshots(withBench);
check(
  JSON.stringify(placed) === JSON.stringify([null, 10_000, 10_050, 9_900]),
  `each close at its nearest snapshot: ${JSON.stringify(placed)}`,
);

const option = equityOption(withBench, [order]);
const lines = option.series as LineSeriesOption[];
check(lines.length === 2, `equity and benchmark: ${lines.length}`);
check(lines[1].name === "Hold the list", `named: ${String(lines[1].name)}`);
check(lines[1].connectNulls === true, "joins across empty slots");
check((lines[1].lineStyle as { type?: string }).type === "dashed", "dashed");
check(option.legend !== undefined, "legend on with two lines");
const xAxis = option.xAxis as { data: string[] };
const plainAxis = plain.xAxis as { data: string[] };
check(JSON.stringify(xAxis.data) === JSON.stringify(plainAxis.data), "axis labels unchanged");
const pins = (lines[0].markPoint as { data: { coord: unknown[] }[] }).data;
check(pins.length === 1 && pins[0].coord[0] === xAxis.data[1], "order pin unchanged");

// An empty or null benchmark is no line at all.
for (const benchmark of [[], null]) {
  const none = equityOption({ ...bare, benchmark }).series as LineSeriesOption[];
  check(none.length === 1, `no line for ${JSON.stringify(benchmark)}`);
}

// A cancelled, expired or rejected order that filled nothing gets no pin; one
// that filled part before it was cancelled, or was never asked about, does.
const cancelled = { ...order, status: "canceled", filled_qty: 0 };
const noPins = equityOption(bare, [cancelled]).series as LineSeriesOption[];
check(noPins[0].markPoint === undefined, "a cancelled unfilled order has no pin");
for (const status of ["expired", "rejected"]) {
  check(!orderTraded({ ...order, status, filled_qty: null }), `${status} unfilled: no pin`);
}
check(orderTraded({ ...order, status: "canceled", filled_qty: 1 }), "a partial fill keeps its pin");
check(orderTraded({ ...order, status: null }), "an order not asked about keeps its pin");
const mixedPins = equityOption(bare, [order, cancelled]).series as LineSeriesOption[];
const kept = (mixedPins[0].markPoint as { data: unknown[] }).data;
check(kept.length === 1, `only the traded order is pinned: ${kept.length}`);
