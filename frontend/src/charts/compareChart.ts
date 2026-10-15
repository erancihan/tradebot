import type { EChartsOption } from "echarts";

import type { EquityCurve } from "../types";
import { axisLabels } from "./equityChart";
import { baseLineOption, LINE_COLORS } from "./theme";

const BENCHMARK_COLOR = "#cbd5e1"; // slate-300: neutral, so it reads as the yardstick

export interface NamedCurve {
  name: string;
  curve: EquityCurve;
  benchmark?: boolean; // drawn dashed and neutral
  highlight?: boolean; // the person's own plan: drawn thicker
}

/**
 * Several equity curves over the same bars (the What-if comparison). Every
 * curve shares the first one's axis: a comparison replays one window, so the
 * indexes match, and `axisLabels` keeps daily data to dates only.
 */
export function multiCurveOption(curves: NamedCurve[]): EChartsOption {
  const option = baseLineOption();
  option.xAxis = { ...option.xAxis, data: axisLabels(curves[0]?.curve.index ?? []) };
  option.legend = { textStyle: { color: "#cbd5e1" }, top: 0, type: "scroll" };
  option.grid = { ...option.grid, top: 36 };
  let colorIndex = 0;
  option.series = curves.map((c) => {
    const color = c.benchmark
      ? BENCHMARK_COLOR
      : LINE_COLORS[colorIndex++ % LINE_COLORS.length];
    return {
      name: c.name,
      type: "line" as const,
      smooth: true,
      showSymbol: false,
      lineStyle: {
        color,
        width: c.highlight ? 3 : 2,
        type: c.benchmark ? ("dashed" as const) : ("solid" as const),
      },
      itemStyle: { color },
      data: c.curve.equity,
    };
  });
  return option;
}
