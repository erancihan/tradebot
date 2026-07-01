import type { EChartsOption, MarkPointComponentOption } from "echarts";

import type { Candle, OrderRow } from "../types";
import { AXIS_COLOR, TEXT_COLOR } from "./theme";

const UP = "#34d399";   // emerald
const DOWN = "#f43f5e"; // rose

function shortTs(ts: string): string {
  return ts.slice(0, 19).replace("T", " ");
}

function orderMarks(candles: Candle[], orders: OrderRow[]): MarkPointComponentOption | undefined {
  if (orders.length === 0 || candles.length === 0) {
    return undefined;
  }
  const times = candles.map((c) => Date.parse(c.ts));
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
    const candle = candles[best];
    const buy = order.side === "buy";
    return {
      name: `${order.side} ${order.qty}`,
      // Buys sit under the bar's low, sells above the high.
      coord: [shortTs(candle.ts), buy ? candle.low : candle.high],
      value: buy ? "B" : "S",
      symbol: "pin" as const,
      symbolSize: 24,
      itemStyle: { color: buy ? UP : DOWN },
    };
  });
  return { label: { color: "#0f172a", fontSize: 10, fontWeight: "bold" }, data };
}

export function candleOption(candles: Candle[], orders: OrderRow[]): EChartsOption {
  return {
    backgroundColor: "transparent",
    grid: { left: 56, right: 16, top: 16, bottom: 56 },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    textStyle: { color: TEXT_COLOR },
    xAxis: {
      type: "category",
      data: candles.map((c) => shortTs(c.ts)),
      axisLine: { lineStyle: { color: AXIS_COLOR } },
      axisLabel: { color: TEXT_COLOR },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: AXIS_COLOR, opacity: 0.4 } },
      axisLabel: { color: TEXT_COLOR },
    },
    dataZoom: [{ type: "inside" }, { type: "slider", bottom: 8, height: 18 }],
    series: [
      {
        type: "candlestick",
        data: candles.map((c) => [c.open, c.close, c.low, c.high]),
        itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
        markPoint: orderMarks(candles, orders),
      },
    ],
  };
}
