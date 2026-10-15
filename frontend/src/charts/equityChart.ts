import type { EChartsOption, MarkPointComponentOption } from "echarts";

import type {
  ArenaRunDetail,
  EquityCurve,
  EquitySeries,
  OrderRow,
  SeasonCurve,
} from "../types";
import { baseLineOption, LINE_COLORS, TEXT_COLOR } from "./theme";

function shortTs(ts: string): string {
  return ts.slice(0, 19).replace("T", " ");
}

/**
 * Axis labels for a series of timestamps. Daily bars carry a clock time that
 * is only the session's UTC stamp (04:00 or 05:00 with DST), so when no two
 * points fall on the same date the time is noise and the label is the date.
 * Intraday series (several points a day) keep the time.
 */
export function axisLabels(timestamps: string[]): string[] {
  const dates = timestamps.map((ts) => ts.slice(0, 10));
  const daily = new Set(dates).size === dates.length;
  return daily ? dates : timestamps.map(shortTs);
}

/** Place each order on the equity line at its nearest-in-time snapshot. */
function orderMarkPoints(
  series: EquitySeries,
  orders: OrderRow[],
  labels: string[],
): MarkPointComponentOption | undefined {
  if (orders.length === 0 || series.points.length === 0) {
    return undefined;
  }
  const times = series.points.map((p) => Date.parse(p.ts));
  const data = orders.map((order) => {
    const t = Date.parse(order.ts);
    let best = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < times.length; i += 1) {
      const diff = Math.abs(times[i] - t);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    }
    const point = series.points[best];
    const buy = order.side === "buy";
    return {
      name: `${order.side} ${order.qty} ${order.symbol}`,
      coord: [labels[best], point.equity],
      value: buy ? "B" : "S",
      symbol: "pin" as const,
      symbolSize: 26,
      itemStyle: { color: buy ? "#34d399" : "#f43f5e" },
    };
  });
  return { label: { color: "#0f172a", fontSize: 10, fontWeight: "bold" }, data };
}

/** ECharts option for a single {index, equity} curve (the run page). */
export function curveOption(name: string, curve: EquityCurve): EChartsOption {
  const option = baseLineOption();
  option.xAxis = { ...option.xAxis, data: axisLabels(curve.index) };
  option.series = [
    {
      name,
      type: "line",
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.08 },
      lineStyle: { color: LINE_COLORS[0], width: 2 },
      itemStyle: { color: LINE_COLORS[0] },
      data: curve.equity,
    },
  ];
  return option;
}

/** The what-if chart: the plan against its buy-and-hold benchmark, same bars. */
export function comparisonOption(plan: EquityCurve, benchmark: EquityCurve | null): EChartsOption {
  const option = curveOption("Your plan", plan);
  if (!benchmark) return option;
  option.legend = { textStyle: { color: "#cbd5e1" }, top: 0 };
  option.grid = { ...option.grid, top: 36 };
  const series = Array.isArray(option.series) ? option.series : [];
  option.series = [
    ...series,
    {
      name: "Buy and hold",
      type: "line",
      smooth: true,
      showSymbol: false,
      lineStyle: { color: LINE_COLORS[1], width: 2, type: "dashed" },
      itemStyle: { color: LINE_COLORS[1] },
      data: benchmark.equity,
    },
  ];
  return option;
}

/** A session date's close as an instant: 20:00 UTC, near the US close. */
function closeTime(day: string): number {
  return Date.parse(`${day.slice(0, 10)}T20:00:00Z`);
}

/**
 * The daily benchmark on the snapshots' category axis: each close sits at
 * its nearest-in-time snapshot (a later close wins a shared slot), every
 * other slot is null and the line joins across them. The axis stays the
 * snapshots', so the labels and order pins are unchanged.
 */
export function benchmarkOnSnapshots(series: EquitySeries): (number | null)[] {
  const times = series.points.map((p) => Date.parse(p.ts));
  const data: (number | null)[] = times.map(() => null);
  for (const point of series.benchmark ?? []) {
    const t = closeTime(point.ts);
    let best = -1;
    let bestDiff = Infinity;
    times.forEach((time, i) => {
      const diff = Math.abs(time - t);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    });
    if (best >= 0) data[best] = point.value;
  }
  return data;
}

/** ECharts option for the equity curve with buy/sell markers and, when the
 * API sent one, the dashed "Hold the list" benchmark (dashboard, History). */
export function equityOption(series: EquitySeries, orders: OrderRow[] = []): EChartsOption {
  const option = baseLineOption();
  const labels = axisLabels(series.points.map((p) => p.ts));
  option.xAxis = { ...option.xAxis, data: labels };
  option.series = [
    {
      name: "Equity",
      type: "line",
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.08 },
      lineStyle: { color: LINE_COLORS[0], width: 2 },
      itemStyle: { color: LINE_COLORS[0] },
      data: series.points.map((p) => p.equity),
      markPoint: orderMarkPoints(series, orders, labels),
    },
  ];
  if (series.benchmark?.length && series.points.length) {
    option.legend = { textStyle: { color: "#cbd5e1" }, top: 0 };
    option.grid = { ...option.grid, top: 36 };
    option.series.push({
      name: "Hold the list",
      type: "line",
      showSymbol: false,
      connectNulls: true,
      lineStyle: { color: LINE_COLORS[1], width: 2, type: "dashed" },
      itemStyle: { color: LINE_COLORS[1] },
      data: benchmarkOnSnapshots(series),
    });
  }
  return option;
}

/** ECharts option for contestants' total-return over a live season's steps. */
export function seasonOption(curves: SeasonCurve[]): EChartsOption {
  const option = baseLineOption();
  // The union of every contestant's steps, not the longest single run. A
  // contestant that errored or timed out on a tick is simply absent from that
  // standings snapshot, so its `steps` has holes — and picking one curve's
  // steps as the axis would leave the others describing different ticks.
  const steps = [...new Set(curves.flatMap((c) => c.steps))].sort((a, b) => a - b);
  option.xAxis = { ...option.xAxis, data: steps.map((s) => `#${s}`) };
  option.yAxis = {
    ...option.yAxis,
    axisLabel: { color: TEXT_COLOR, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
  };
  option.legend = { textStyle: { color: "#cbd5e1" }, top: 0 };
  option.grid = { ...option.grid, top: 36 };
  option.series = curves.map((curve, i) => ({
    name: curve.name,
    type: "line",
    smooth: true,
    showSymbol: false,
    lineStyle: { color: LINE_COLORS[i % LINE_COLORS.length], width: 2 },
    itemStyle: { color: LINE_COLORS[i % LINE_COLORS.length] },
    // Placed BY STEP, never by position. Feeding the raw array lets ECharts
    // map index 0 to the first tick of the season rather than to this
    // contestant's first tick, which silently slides a late joiner's whole
    // curve to the left and makes it look like it was scoring when it was not
    // even running. `null` leaves an honest gap.
    data: alignToSteps(curve, steps),
  }));
  return option;
}

/** A curve's values placed against a shared step axis, with gaps for missing ticks. */
function alignToSteps(curve: SeasonCurve, steps: number[]): (number | null)[] {
  const byStep = new Map<number, number>();
  curve.steps.forEach((step, i) => {
    const value = curve.total_return[i];
    if (value !== undefined) byStep.set(step, value);
  });
  return steps.map((step) => byStep.get(step) ?? null);
}

/** ECharts option for many contestants' equity curves (the arena). */
export function arenaOption(detail: ArenaRunDetail): EChartsOption {
  const option = baseLineOption();
  const longest = detail.curves.reduce<string[]>(
    (acc, c) => (c.index.length > acc.length ? c.index : acc),
    [],
  );
  option.xAxis = { ...option.xAxis, data: axisLabels(longest) };
  option.legend = { textStyle: { color: "#cbd5e1" }, top: 0 };
  option.grid = { ...option.grid, top: 36 };
  option.series = detail.curves.map((curve, i) => ({
    name: curve.name,
    type: "line",
    smooth: true,
    showSymbol: false,
    lineStyle: { color: LINE_COLORS[i % LINE_COLORS.length], width: 2 },
    itemStyle: { color: LINE_COLORS[i % LINE_COLORS.length] },
    data: curve.equity,
  }));
  return option;
}
