// The dashboard equity chart: loads /api/equity and re-renders on mode change.

import * as echarts from "echarts";

import { getEquity, getOrders } from "../api/client";
import { live, refs } from "../alpine";
import { equityOption } from "../charts/equityChart";
import { LIVE_TICK } from "../sse";

type Chart = ReturnType<typeof echarts.init>;

export function equityChart() {
  return {
    mode: "",
    chart: null as Chart | null,
    async init() {
      this.chart = echarts.init(refs(this).chart);
      await this.load();
      window.addEventListener("resize", () => this.chart?.resize());
      // Refresh the curve on each SSE heartbeat so a running session updates live.
      window.addEventListener(LIVE_TICK, () => {
        if (live(this).enabled) {
          void this.load();
        }
      });
    },
    async setMode(mode: string) {
      this.mode = mode;
      await this.load();
    },
    async load() {
      const mode = this.mode || undefined;
      const [series, orders] = await Promise.all([getEquity(mode), getOrders(mode)]);
      this.chart?.setOption(equityOption(series, orders), true);
    },
  };
}
