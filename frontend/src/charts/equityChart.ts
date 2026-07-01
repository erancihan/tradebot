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

/** Place each order on the equity line at its nearest-in-time snapshot. */
function orderMarkPoints(
  series: EquitySeries,
  orders: OrderRow[],
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
      coord: [shortTs(point.ts), point.equity],
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
  option.xAxis = { ...option.xAxis, data: curve.index.map(shortTs) };
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

/** ECharts option for a single equity curve with buy/sell markers (dashboard). */
export function equityOption(series: EquitySeries, orders: OrderRow[] = []): EChartsOption {
  const option = baseLineOption();
  option.xAxis = { ...option.xAxis, data: series.points.map((p) => shortTs(p.ts)) };
  option.series = [
    {
      name: "equity",
      type: "line",
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.08 },
      lineStyle: { color: LINE_COLORS[0], width: 2 },
      itemStyle: { color: LINE_COLORS[0] },
      data: series.points.map((p) => p.equity),
      markPoint: orderMarkPoints(series, orders),
    },
  ];
  return option;
}

/** ECharts option for contestants' total-return over a live season's steps. */
export function seasonOption(curves: SeasonCurve[]): EChartsOption {
  const option = baseLineOption();
  const steps = curves.reduce<number[]>(
    (acc, c) => (c.steps.length > acc.length ? c.steps : acc),
    [],
  );
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
    data: curve.total_return,
  }));
  return option;
}

/** ECharts option for many contestants' equity curves (the arena). */
export function arenaOption(detail: ArenaRunDetail): EChartsOption {
  const option = baseLineOption();
  const longest = detail.curves.reduce<string[]>(
    (acc, c) => (c.index.length > acc.length ? c.index : acc),
    [],
  );
  option.xAxis = { ...option.xAxis, data: longest.map(shortTs) };
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
