// The arena chart: overlays every contestant's equity curve for one run.

import * as echarts from "echarts";

import { getArenaRun } from "../api/client";
import { refs } from "../alpine";
import { arenaOption } from "../charts/equityChart";

type Chart = ReturnType<typeof echarts.init>;

export function arenaChart(runId: number) {
  return {
    chart: null as Chart | null,
    async init() {
      this.chart = echarts.init(refs(this).chart);
      const detail = await getArenaRun(runId);
      this.chart.setOption(arenaOption(detail), true);
      window.addEventListener("resize", () => this.chart?.resize());
    },
  };
}
