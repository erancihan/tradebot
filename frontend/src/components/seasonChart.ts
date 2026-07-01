// Multi-line chart of each contestant's total-return across a live season.

import * as echarts from "echarts";

import { getSeasonDetail } from "../api/client";
import { refs } from "../alpine";
import { seasonOption } from "../charts/equityChart";

type Chart = ReturnType<typeof echarts.init>;

export function seasonChart(seasonId: number) {
  return {
    chart: null as Chart | null,
    async init() {
      if (!seasonId) {
        return;
      }
      this.chart = echarts.init(refs(this).chart);
      const detail = await getSeasonDetail(seasonId);
      this.chart.setOption(seasonOption(detail.curves), true);
      window.addEventListener("resize", () => this.chart?.resize());
    },
  };
}
