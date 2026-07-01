// Candlestick price chart for one symbol, with buy/sell order pins overlaid.

import * as echarts from "echarts";

import { getBars, getOrders } from "../api/client";
import { refs } from "../alpine";
import { candleOption } from "../charts/candleChart";

type Chart = ReturnType<typeof echarts.init>;

export function candleChart(initialSymbol: string) {
  return {
    symbol: initialSymbol,
    chart: null as Chart | null,
    async init() {
      if (!this.symbol) {
        return; // no bar data yet — the template shows an empty state
      }
      this.chart = echarts.init(refs(this).chart);
      await this.load();
      window.addEventListener("resize", () => this.chart?.resize());
    },
    async setSymbol(symbol: string) {
      this.symbol = symbol;
      await this.load();
    },
    async load() {
      const [bars, orders] = await Promise.all([getBars(this.symbol), getOrders()]);
      const symbolOrders = orders.filter((o) => o.symbol === this.symbol);
      this.chart?.setOption(candleOption(bars.candles, symbolOrders), true);
    },
  };
}
