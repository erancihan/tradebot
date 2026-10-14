// The What-if page: describe a plan, run it on the server, read the result.
//
// Phone first: one column, large inputs, one primary button. The job runs on
// the server (`POST /api/whatif`) and is polled through the shared
// `/api/jobs/{id}`. Every result shows the data it ran on (provenance).

import * as echarts from "echarts";

import { getJob, submitWhatIf } from "../api/client";
import { nextTick, refs } from "../alpine";
import { curveOption } from "../charts/equityChart";
import type { EquityCurve, JobView, Provenance, WhatIfRequest } from "../types";

type Chart = ReturnType<typeof echarts.init>;

const POLL_MS = 500;

interface WhatIfForm {
  symbols: string;
  source: string;
  start: string;
  end: string;
  initial_cash: number;
  monthly_contribution: number;
}

export function whatIf() {
  return {
    form: {
      symbols: "SPY",
      source: "real",
      start: "",
      end: "",
      initial_cash: 10000,
      monthly_contribution: 200,
    } as WhatIfForm,
    state: "idle",
    error: "",
    summary: null as Record<string, number | string> | null,
    provenance: null as Provenance | null,
    chart: null as Chart | null,

    symbolList(): string[] {
      return this.form.symbols
        .split(/[\s,]+/)
        .map((s) => s.trim().toUpperCase())
        .filter((s) => s.length > 0);
    },

    buildRequest(): WhatIfRequest {
      const f = this.form;
      const req: WhatIfRequest = {
        symbols: this.symbolList(),
        source: f.source,
        initial_cash: f.initial_cash,
        monthly_contribution: f.monthly_contribution,
      };
      if (f.start) req.start = f.start;
      if (f.end) req.end = f.end;
      return req;
    },

    async submit() {
      this.state = "running";
      this.error = "";
      this.summary = null;
      this.provenance = null;
      try {
        const { job_id } = await submitWhatIf(this.buildRequest());
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
        this.provenance = job.provenance ?? null;
        if (job.equity) await this.render(job.equity);
      } else if (job.state === "error") {
        this.state = "error";
        this.error = job.error ?? "job failed";
      } else {
        setTimeout(() => {
          void this.poll(jobId);
        }, POLL_MS);
      }
    },

    money(key: string): string {
      const v = Number(this.summary?.[key] ?? 0);
      return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    },

    pct(key: string): string {
      const v = Number(this.summary?.[key] ?? 0);
      return `${(v * 100).toFixed(1)}%`;
    },

    provenanceLabel(): string {
      const p = this.provenance;
      if (!p) return "";
      const window = `${p.start.slice(0, 10)} → ${p.end.slice(0, 10)}`;
      const kind = p.source === "real" ? "REAL" : "SYNTHETIC";
      return `${kind} · ${p.symbol} · ${window} · ${p.bars} bars`;
    },

    async render(curve: EquityCurve) {
      await nextTick(this);
      if (!this.chart) this.chart = echarts.init(refs(this).chart);
      this.chart.setOption(curveOption("plan", curve), true);
      this.chart.resize();
    },
  };
}
