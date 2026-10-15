// History page: the performance card, its equity chart, and the timeline of
// orders and proposal batches. The markup is server-rendered
// (components/history_*.html). "Show more" appends the next page; the poll
// refreshes the newest page only while no older page has been appended, so
// the list never jumps under someone reading back through it.

import * as echarts from "echarts";

import { getEquity, getHistoryPage, getPartial } from "../api/client";
import { el, refs } from "../alpine";
import { equityOption } from "../charts/equityChart";

const POLL_MS = 30_000;
const FIRST_PAGE = "/partials/history";

type Chart = ReturnType<typeof echarts.init>;

export function history() {
  // ECharts must not live in Alpine state (a Proxy): keep it in this closure.
  let chart: Chart | null = null;

  return {
    mode: "",
    next: "",
    pages: 1,
    busy: false,
    error: "",

    init() {
      const data = el(this).dataset;
      this.mode = data.mode ?? "";
      this.next = data.next ?? "";
      const box = refs(this).chart;
      if (box) {
        chart = echarts.init(box);
        window.addEventListener("resize", () => chart?.resize());
        void this.drawChart();
      }
      window.setInterval(() => void this.poll(), POLL_MS);
    },

    async more() {
      if (!this.next || this.busy) return;
      this.busy = true;
      this.error = "";
      try {
        const page = await getHistoryPage(this.next);
        refs(this).list.insertAdjacentHTML("beforeend", page.html);
        this.next = page.next;
        this.pages += 1;
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.busy = false;
      }
    },

    async poll() {
      if (this.pages > 1 || this.busy) return;
      try {
        const page = await getHistoryPage(FIRST_PAGE);
        // A "Show more" that finished while this was in flight wins.
        if (this.pages > 1) return;
        refs(this).list.innerHTML = page.html;
        this.next = page.next;
        const card = refs(this).performance;
        if (card) card.innerHTML = await getPartial("/partials/history/performance");
        await this.drawChart();
      } catch (err) {
        console.error(err);
      }
    },

    async drawChart() {
      if (!chart) return;
      const series = await getEquity(this.mode || undefined);
      chart.setOption(equityOption(series), true);
    },
  };
}
