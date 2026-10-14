// The What-if page: describe a plan, run it on the server, read the result.
//
// Phone first: one column, large inputs, one primary button. The job runs on
// the server (`POST /api/whatif`) and is polled through the shared
// `/api/jobs/{id}`. Every result shows the data it ran on (provenance).

import * as echarts from "echarts";

import { getCache, getJob, getStrategies, submitWhatIf } from "../api/client";
import { el, nextTick, refs } from "../alpine";
import { comparisonOption } from "../charts/equityChart";
import type {
  CacheEntry,
  EquityCurve,
  JobView,
  Provenance,
  StrategyParam,
  StrategySpec,
  WhatIfPreset,
  WhatIfRequest,
} from "../types";

type Chart = ReturnType<typeof echarts.init>;

const POLL_MS = 500;

interface WhatIfForm {
  symbols: string;
  source: string;
  start: string;
  end: string;
  initial_cash: number;
  monthly_contribution: number;
  strategy: string;
  allocation: string;
  selector: string; // "" = hold every symbol
  top_k: number;
}

export function whatIf() {
  // Kept out of Alpine's reactive state: a proxied ECharts instance breaks on
  // multi-series updates (its internals compare objects by identity).
  let chart: Chart | null = null;
  return {
    form: {
      symbols: "SPY",
      source: "real",
      start: "",
      end: "",
      initial_cash: 10000,
      monthly_contribution: 200,
      strategy: "buy_and_hold",
      allocation: "equal",
      selector: "",
      top_k: 2,
    } as WhatIfForm,
    strategies: [] as StrategySpec[],
    cache: [] as CacheEntry[],
    presets: [] as WhatIfPreset[],
    params: {} as Record<string, number | boolean | string>,
    // Selector settings a preset carries beyond `top_k` (lookback, skip).
    selectorExtras: {} as Record<string, number>,
    state: "idle",
    error: "",
    summary: null as Record<string, number | string> | null,
    provenance: null as Provenance | null,

    async init() {
      this.presets = readPresets(el(this));
      try {
        [this.strategies, this.cache] = await Promise.all([getStrategies(), getCache()]);
      } catch {
        // Catalog or cache list unreachable: the form still submits.
      }
      if (this.presets.length > 0) this.applyPreset(0);
      else this.syncParams();
    },

    applyPreset(index: number) {
      const preset = this.presets[index];
      if (!preset) return;
      const r = preset.request;
      this.form.symbols = r.symbols.join(" ");
      this.form.source = r.source;
      this.form.start = r.start ?? "";
      this.form.end = r.end ?? "";
      this.form.initial_cash = r.initial_cash;
      this.form.monthly_contribution = r.monthly_contribution;
      this.form.strategy = r.strategy;
      this.form.allocation = r.allocation;
      this.form.selector = r.selector ?? "";
      this.form.top_k = r.selector_params.top_k ?? 2;
      this.syncParams();
      this.params = { ...this.params, ...r.params };
      this.selectorExtras = { ...r.selector_params };
    },

    // A preset's extra selector settings belong to that selector only.
    clearSelectorExtras() {
      this.selectorExtras = {};
    },

    // Cached daily entries for the typed symbols (real data only).
    cachedEntries(): CacheEntry[] {
      return this.cache.filter(
        (e) => e.timeframe === "1day" && this.symbolList().includes(e.symbol),
      );
    },

    missingSymbols(): string[] {
      const have = new Set(this.cachedEntries().map((e) => e.symbol));
      return this.symbolList().filter((s) => !have.has(s));
    },

    // The window every typed symbol has on disk: the date inputs' min and max.
    minDate(): string {
      const firsts = this.cachedEntries().map((e) => e.first.slice(0, 10));
      return this.form.source === "real" && firsts.length ? firsts.sort()[firsts.length - 1] : "";
    },

    maxDate(): string {
      const lasts = this.cachedEntries().map((e) => e.last.slice(0, 10));
      return this.form.source === "real" && lasts.length ? lasts.sort()[0] : "";
    },

    // The exact pull command when the cache cannot serve the plan as typed —
    // shown before running, so nobody waits for a job that must fail.
    pullHint(): string {
      if (this.form.source !== "real" || this.symbolList().length === 0) return "";
      const lo = this.minDate();
      const hi = this.maxDate();
      const outside =
        (this.form.start !== "" && lo !== "" && this.form.start < lo) ||
        (this.form.end !== "" && hi !== "" && this.form.end > hi);
      const missing = this.missingSymbols();
      if (missing.length === 0 && !outside) return "";
      const symbols = missing.length ? missing : this.symbolList();
      const parts = [`tradebot data pull --symbols ${symbols.join(" ")}`, "--timeframe 1day"];
      if (this.form.start) parts.push(`--start ${this.form.start}`);
      if (this.form.end) parts.push(`--end ${this.form.end}`);
      return parts.join(" ");
    },

    // Buy and hold is the first, fixed option; the registry fills the rest.
    otherStrategies(): StrategySpec[] {
      return this.strategies.filter((s) => s.name !== "buy_and_hold");
    },

    currentParams(): StrategyParam[] {
      return this.strategies.find((s) => s.name === this.form.strategy)?.params ?? [];
    },

    syncParams() {
      const fresh: Record<string, number | boolean | string> = {};
      for (const p of this.currentParams()) fresh[p.name] = p.default;
      this.params = fresh;
    },

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
        strategy: f.strategy,
        params: { ...this.params },
        allocation: f.allocation,
      };
      if (f.selector) {
        req.selector = f.selector;
        req.selector_params = { ...this.selectorExtras, top_k: f.top_k };
      }
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
        if (job.equity) await this.render(job.equity, job.benchmark ?? null);
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

    // Signed percentage for the "vs buy and hold" line: +3.2% / -1.5%.
    signedPct(key: string): string {
      const v = Number(this.summary?.[key] ?? 0) * 100;
      return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
    },

    beatsBenchmark(): boolean {
      return Number(this.summary?.vs_benchmark_pct ?? 0) >= 0;
    },

    async render(curve: EquityCurve, benchmark: EquityCurve | null) {
      await nextTick(this);
      if (!chart) chart = echarts.init(refs(this).chart);
      chart.setOption(comparisonOption(curve, benchmark), true);
      chart.resize();
    },
  };
}

// Presets are rendered by the server into a data attribute (no inline JS), so
// the buttons and this list come from one call and cannot disagree.
function readPresets(root: HTMLElement): WhatIfPreset[] {
  try {
    return JSON.parse(root.dataset.presets ?? "[]") as WhatIfPreset[];
  } catch {
    return [];
  }
}
