// Compare strategies: the ranked table, the chart's lines, and failures that
// must end as the page's error text instead of a spinning button.

import { multiCurveOption } from "../src/charts/compareChart";
import { whatIf } from "../src/components/whatif";
import {
  BENCHMARK_LABEL,
  compareCurves,
  compareTable,
  settleCompare,
} from "../src/components/whatifCompare";
import type { CompareRow, EquityCurve, WhatIfCompare } from "../src/types";
import { check, json, sleep, stubFetch } from "./harness";

function row(name: string, final_value: number, benchmark = false): CompareRow {
  const r: CompareRow = { name, final_value, gain: final_value - 1000, cagr: 0.1,
                          max_drawdown: -0.1, vs_benchmark_pct: 0 };
  if (benchmark) r.benchmark = true;
  return r;
}

const curve = (v: number): EquityCurve => ({
  index: ["2024-01-02T05:00:00+00:00", "2024-01-03T05:00:00+00:00"],
  equity: [1000, v],
});

const names = ["momentum", "supertrend", "buy_and_hold", "rsi", "macd", "sma"];
const values = [1500, 1400, 1200, 1100, 1050, 900];
const compare: WhatIfCompare = {
  rows: names.map((n, i) => row(n, values[i])),
  benchmark: row("benchmark", 1200, true),
  curves: Object.fromEntries([
    ...names.slice(0, 5).map((n, i) => [n, curve(values[i])]),
    ["benchmark", curve(1200)],
  ]),
  errors: [],
  skipped: [{ name: "follow_leader", reason: "needs a roster" }],
  plan_strategy: "rsi",
};

// The table merges the benchmark in rank order; a tie keeps the strategy first.
const table = compareTable(compare).map((r) => r.name);
check(table.length === 7, `six strategies and the benchmark, got ${table.length}`);
check(table.indexOf("buy_and_hold") === table.indexOf("benchmark") - 1,
      `a tie ranks the strategy above the benchmark: ${table.join(",")}`);
check(table[0] === "momentum" && table[6] === "sma", `best first: ${table.join(",")}`);
check(compareTable(null).length === 0, "no comparison, no rows");

// The chart: top five in rank order, the plan's own line thicker, benchmark last.
const lines = compareCurves(compare);
check(lines.length === 6, `five strategies and the benchmark, got ${lines.length}`);
check(lines[5].name === BENCHMARK_LABEL && lines[5].benchmark === true, "benchmark last");
check(lines.find((l) => l.name === "rsi")?.highlight === true, "the plan's line is highlighted");
const option = multiCurveOption(lines);
const series = Array.isArray(option.series) ? option.series : [];
check(series.length === 6, `six series, got ${series.length}`);
const xAxis = option.xAxis as { data: string[] };
check(xAxis.data[0] === "2024-01-02", `daily data shows dates only: ${xAxis.data[0]}`);

// A finished job settles the page into the compare view.
const host = { state: "running", error: "", provenance: null, view: "compare",
               compare: null as WhatIfCompare | null, buildRequest: () => ({
                 symbols: ["SPY"], source: "synthetic", initial_cash: 1, monthly_contribution: 0 }) };
check(settleCompare(host, { id: "j", kind: "whatif_compare", state: "done", compare }),
      "a done job settles");
check(host.state === "done" && host.compare === compare, "done job fills the comparison");
const texts = whatIf();
texts.compare = compare;
check(texts.skippedText() === "Not run: follow_leader (needs a roster)", texts.skippedText());
check(texts.errorsText() === "", "no failures, no failure line");
check(texts.isPlanRow(compare.rows[3]) && !texts.isPlanRow(compare.benchmark),
      "only the plan's own strategy row is highlighted");
check(!settleCompare(host, { id: "j", kind: "whatif_compare", state: "error", error: "boom" }),
      "an error job does not settle as done");
check(host.state === "error" && host.error === "boom", "the job's error is the page's error");

// A failed poll ends in "error" with the failure as the page's error text.
let polls = 0;
stubFetch((url) => {
  if (url === "/api/whatif/compare") return json({ job_id: "c1" });
  if (url === "/api/jobs/c1") {
    polls += 1;
    return polls === 1 ? json({ id: "c1", state: "running" }) : json({}, 500);
  }
  return json({}, 404);
});
const page = whatIf();
await page.submitCompare();
await sleep(50);
check(polls === 2, `polled twice, got ${polls}`);
check(page.state === "error", `state is "error", got "${page.state}"`);
check(page.view === "compare", `the compare view is the one that failed, got "${page.view}"`);
check(page.error.includes("500"), `the error names the failure: "${page.error}"`);

// A refused plan (400) never starts polling and shows the refusal.
stubFetch(() => json({ detail: "give between 1 and 12 symbols" }, 400));
await page.submitCompare();
check(page.state === "error", `a refused plan ends in "error", got "${page.state}"`);
check(page.error.length > 0, "the refusal is shown");
