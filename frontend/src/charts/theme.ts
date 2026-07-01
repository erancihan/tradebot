import type { EChartsOption } from "echarts";

// A dark, minimal base shared by every chart so they look consistent.
export const AXIS_COLOR = "#334155"; // slate-700
export const TEXT_COLOR = "#94a3b8"; // slate-400
export const LINE_COLORS = ["#34d399", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa"];

export function baseLineOption(): EChartsOption {
  return {
    backgroundColor: "transparent",
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    tooltip: { trigger: "axis" },
    textStyle: { color: TEXT_COLOR },
    xAxis: {
      type: "category",
      boundaryGap: false,
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisLabel: { color: TEXT_COLOR },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: AXIS_COLOR, opacity: 0.4 } },
      axisLabel: { color: TEXT_COLOR },
    },
  };
}
