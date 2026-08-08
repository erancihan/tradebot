// Submits a backtest/dry-run job, polls until it finishes, and renders the
// resulting summary + equity curve — with the provenance of the data it ran on.
//
// Two sources. "synthetic" invents a seeded path on an artificial calendar;
// "real" replays bars from the local cache only. The dashboard never fetches:
// when a range isn't cached, the UI shows the exact `tradebot data pull`
// command instead of reaching for the network.

import * as echarts from "echarts";

import { getCache, getJob, getStrategies, submitJob } from "../api/client";
import { nextTick, refs } from "../alpine";
import { curveOption } from "../charts/equityChart";
import type {
  CacheEntry,
  JobRequest,
  JobView,
  Provenance,
  StrategyParam,
  StrategySpec,
} from "../types";

type Chart = ReturnType<typeof echarts.init>;

const POLL_MS = 500;

interface FormState {
  kind: string;
  strategy: string;
  source: string;
  periods: number;
  seed: number;
  symbol: string;
  start: string;
  end: string;
  initial_cash: number;
}

export function jobRunner() {
  return {
    form: {
      kind: "backtest",
      strategy: "sma_crossover",
      source: "synthetic",
      periods: 500,
      seed: 42,
      symbol: "",
      start: "",
      end: "",
      initial_cash: 10000,
    } as FormState,
    strategies: [] as StrategySpec[],
    cache: [] as CacheEntry[],
    params: {} as Record<string, number | boolean | string>,
    state: "idle",
    error: "",
    summary: null as Record<string, number | string> | null,
    provenance: null as Provenance | null,
    chart: null as Chart | null,

    async init() {
      try {
        [this.strategies, this.cache] = await Promise.all([
          getStrategies(),
          getCache(),
        ]);
      } catch {
        // Endpoints unreachable: the form still submits with typed-in values.
      }
      this.syncParams();
      this.syncSymbol();
    },

    spec(): StrategySpec | undefined {
      return this.strategies.find((s) => s.name === this.form.strategy);
    },

    currentParams(): StrategyParam[] {
      return this.spec()?.params ?? [];
    },

    syncParams() {
      const fresh: Record<string, number | boolean | string> = {};
      for (const p of this.currentParams()) {
        fresh[p.name] = p.default;
      }
      this.params = fresh;
    },

    entry(): CacheEntry | undefined {
      return this.cache.find((e) => e.symbol === this.form.symbol);
    },

    // Default the symbol and date range to what the cache can actually serve.
    syncSymbol() {
      if (this.cache.length && !this.form.symbol) {
        this.form.symbol = this.cache[0].symbol;
      }
      const entry = this.entry();
      if (entry) {
        this.form.start = entry.first.slice(0, 10);
        this.form.end = entry.last.slice(0, 10);
      }
    },

    // The exact command that would fill the cache for the requested range —
    // shown instead of fetching, so the dashboard stays credential-free.
    pullHint(): string {
      const symbol = this.form.symbol || "SPY";
      const parts = [`tradebot data pull --symbols ${symbol}`, "--timeframe 1day"];
      if (this.form.start) parts.push(`--start ${this.form.start}`);
      if (this.form.end) parts.push(`--end ${this.form.end}`);
      return parts.join(" ");
    },

    buildRequest(): JobRequest {
      const f = this.form;
      const req: JobRequest = {
        kind: f.kind,
        strategy: f.strategy,
        source: f.source,
        periods: f.periods,
        seed: f.seed,
        initial_cash: f.initial_cash,
        params: { ...this.params },
      };
      if (f.source === "real") {
        req.symbol = f.symbol;
        req.timeframe = this.entry()?.timeframe ?? "1day";
        if (f.start) req.start = f.start;
        if (f.end) req.end = f.end;
      }
      return req;
    },

    async submit() {
      this.state = "running";
      this.error = "";
      this.summary = null;
      this.provenance = null;
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
        this.provenance = job.provenance ?? null;
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

    provenanceLabel(): string {
      const p = this.provenance;
      if (!p) return "";
      const window = `${p.start.slice(0, 10)} → ${p.end.slice(0, 10)}`;
      if (p.source === "real") {
        return `REAL · ${p.symbol} · ${window} · ${p.bars} bars`;
      }
      return `SYNTHETIC · seed ${p.seed ?? "?"} · ${window} · ${p.bars} bars`;
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
