// "Compare strategies" on the What-if page: the same plan once per strategy.
//
// Mixed into `whatIf()`: it reuses the form (`buildRequest`) and the page's
// one `state`/`error`/`provenance`, and `view` says which result card shows.
// The job runs on the server (`POST /api/whatif/compare`) and is polled with
// the same `waitForJob` as a single run.

import * as echarts from "echarts";

import { submitWhatIfCompare, waitForJob } from "../api/client";
import { nextTick, refs } from "../alpine";
import { multiCurveOption, type NamedCurve } from "../charts/compareChart";
import type { CompareRow, JobView, Provenance, WhatIfCompare, WhatIfRequest } from "../types";

type Chart = ReturnType<typeof echarts.init>;

export const BENCHMARK_LABEL = "Buy and hold (benchmark)";

// What a comparison needs from the page it is mixed into.
export interface CompareHost {
  state: string;
  error: string;
  provenance: Provenance | null;
  view: string;
  compare: WhatIfCompare | null;
  buildRequest(): WhatIfRequest;
}

/** Every strategy row plus the benchmark, best final value first. */
export function compareTable(compare: WhatIfCompare | null): CompareRow[] {
  if (!compare) return [];
  // A stable sort keeps a tying strategy (buy_and_hold) above the benchmark.
  return [...compare.rows, compare.benchmark].sort((a, b) => b.final_value - a.final_value);
}

/** The chart's lines: the curves the server sent, in rank order, benchmark last. */
export function compareCurves(compare: WhatIfCompare): NamedCurve[] {
  const lines: NamedCurve[] = compare.rows
    .filter((row) => compare.curves[row.name])
    .map((row) => ({
      name: row.name,
      curve: compare.curves[row.name],
      highlight: row.name === compare.plan_strategy,
    }));
  const bench = compare.curves.benchmark;
  if (bench) lines.push({ name: BENCHMARK_LABEL, curve: bench, benchmark: true });
  return lines;
}

// Settles the page from a finished job; returns false when the job failed.
export function settleCompare(host: CompareHost, job: JobView): boolean {
  if (job.state === "error") {
    host.state = "error";
    host.error = job.error ?? "job failed";
    return false;
  }
  host.state = "done";
  host.compare = job.compare ?? null;
  host.provenance = job.provenance ?? null;
  return true;
}

export function compareState() {
  // Kept out of Alpine's reactive state (a Proxy breaks ECharts internals).
  let chart: Chart | null = null;
  return {
    view: "single",
    compare: null as WhatIfCompare | null,

    // Every await sits inside this try, so a failed submit or poll ends as
    // the page's error text instead of a button stuck on "Comparing…".
    async submitCompare(this: CompareHost) {
      this.state = "running";
      this.view = "compare";
      this.error = "";
      this.compare = null;
      this.provenance = null;
      try {
        const { job_id } = await submitWhatIfCompare(this.buildRequest());
        const job = await waitForJob(job_id);
        if (!settleCompare(this, job) || !this.compare) return;
        await nextTick(this);
        if (!chart) chart = echarts.init(refs(this).compareChart);
        chart.setOption(multiCurveOption(compareCurves(this.compare)), true);
        chart.resize();
      } catch (err) {
        this.state = "error";
        this.error = err instanceof Error ? err.message : String(err);
      }
    },

    compareRows(this: CompareHost): CompareRow[] {
      return compareTable(this.compare);
    },

    // Strategies left out, and why (a meta strategy needs a roster).
    skippedText(this: CompareHost): string {
      const skipped = this.compare?.skipped ?? [];
      return skipped.length
        ? `Not run: ${skipped.map((s) => `${s.name} (${s.reason})`).join(", ")}`
        : "";
    },

    // Strategies that raised: the rest of the comparison still ran.
    errorsText(this: CompareHost): string {
      const errors = this.compare?.errors ?? [];
      return errors.length ? `Failed: ${errors.map((e) => `${e.name}: ${e.error}`).join("; ")}` : "";
    },

    rowLabel(row: CompareRow): string {
      return row.benchmark ? BENCHMARK_LABEL : row.name;
    },

    isPlanRow(this: CompareHost, row: CompareRow): boolean {
      return !row.benchmark && row.name === this.compare?.plan_strategy;
    },

    rowMoney(value: number): string {
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    },

    rowPct(value: number): string {
      return `${(value * 100).toFixed(1)}%`;
    },
  };
}
