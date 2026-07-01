// Submits a backtest/dry-run job, polls until it finishes, and renders the
// resulting summary + equity curve.

import * as echarts from "echarts";

import { getJob, submitJob } from "../api/client";
import { nextTick, refs } from "../alpine";
import { curveOption } from "../charts/equityChart";
import type { JobRequest, JobView } from "../types";

type Chart = ReturnType<typeof echarts.init>;

const POLL_MS = 500;

interface FormState {
  kind: string;
  strategy: string;
  periods: number;
  seed: number;
  initial_cash: number;
  fast: number;
  slow: number;
  period: number;
  oversold: number;
}

export function jobRunner() {
  return {
    form: {
      kind: "backtest",
      strategy: "sma_crossover",
      periods: 500,
      seed: 42,
      initial_cash: 10000,
      fast: 20,
      slow: 50,
      period: 14,
      oversold: 30,
    } as FormState,
    state: "idle",
    error: "",
    summary: null as Record<string, number | string> | null,
    chart: null as Chart | null,

    buildRequest(): JobRequest {
      const f = this.form;
      const params: Record<string, number> =
        f.strategy === "sma_crossover"
          ? { fast: f.fast, slow: f.slow }
          : { period: f.period, oversold: f.oversold };
      return {
        kind: f.kind,
        strategy: f.strategy,
        periods: f.periods,
        seed: f.seed,
        initial_cash: f.initial_cash,
        params,
      };
    },

    async submit() {
      this.state = "running";
      this.error = "";
      this.summary = null;
      try {
        const { job_id } = await submitJob(this.buildRequest());
        await this.poll(job_id);
      } catch (err) {
        this.state = "error";
        this.error = String(err);
      }
    },

    async poll(jobId: string) {
      const job: JobView = await getJob(jobId);
      if (job.state === "done") {
        this.state = "done";
        this.summary = job.summary ?? {};
        if (job.equity) {
          await this.render(job.equity);
        }
      } else if (job.state === "error") {
        this.state = "error";
        this.error = job.error ?? "job failed";
      } else {
        setTimeout(() => {
          void this.poll(jobId);
        }, POLL_MS);
      }
    },

    async render(curve: { index: string[]; equity: number[] }) {
      await nextTick(this); // wait for the results block to be shown
      if (!this.chart) {
        this.chart = echarts.init(refs(this).chart);
      }
      this.chart.setOption(curveOption("equity", curve), true);
      this.chart.resize();
    },
  };
}
