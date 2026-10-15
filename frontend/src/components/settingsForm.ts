// The Settings form's model and its two conversions. The server speaks the
// config.yaml document (fractions, nested blocks, null for "unset"); the form
// speaks what a thumb types (percentages, one text box of symbols, "" for
// unset). Converting back starts from the document the server sent, so any key
// the form does not show (overlays, a meta strategy's roster, explicit
// weights) survives a save untouched.

import type { ParamMap, ParamValue, SettingsDoc, StrategyParam } from "../types";

// Risk fields stored as fractions of equity, typed as percentages.
export const PERCENT_FIELDS = [
  "max_position_pct",
  "max_gross_exposure",
  "max_daily_loss_pct",
  "rebalance_band_pct",
  "stop_loss_pct",
  "take_profit_pct",
] as const;

// Bracket legs may be left empty (no bracket); the others always have a value.
const NULLABLE = new Set<string>(["stop_loss_pct", "take_profit_pct"]);

export interface SettingsForm {
  symbols: string;
  timeframe: string;
  poll_seconds: number;
  initial_cash: number;
  market: string;
  brief: string;
  strategy: string;
  strategyParams: Record<string, ParamValue>;
  selector: string;
  selectorParams: Record<string, ParamValue>;
  allocation: string;
  allocationParams: Record<string, ParamValue>;
  riskPct: Record<string, string>;
  allowFractional: boolean;
  webhookUrl: string;
  ntfyTopic: string;
  ntfyServer: string;
}

export function toPercent(fraction: unknown): string {
  return typeof fraction === "number" ? String(Number((fraction * 100).toFixed(6))) : "";
}

export function fromPercent(text: string): number | null {
  const trimmed = String(text).trim();
  return trimmed === "" ? null : Number(trimmed) / 100;
}

export function parseSymbols(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0);
}

// Only the scalar params a form field can hold; richer ones stay in the doc.
function scalars(params: ParamMap | undefined): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {};
  for (const [key, value] of Object.entries(params ?? {})) {
    if (["number", "boolean", "string"].includes(typeof value)) out[key] = value as ParamValue;
  }
  return out;
}

// The defaults a freshly picked component starts from.
export function defaults(params: StrategyParam[]): Record<string, ParamValue> {
  return Object.fromEntries(params.map((p) => [p.name, p.default]));
}

export function toForm(doc: SettingsDoc): SettingsForm {
  const riskPct: Record<string, string> = {};
  for (const key of PERCENT_FIELDS) riskPct[key] = toPercent(doc.risk[key]);
  const brief = doc.autopilot?.brief_minutes_before_open;
  return {
    symbols: doc.symbols.join(", "),
    timeframe: doc.timeframe,
    poll_seconds: doc.poll_seconds,
    initial_cash: doc.initial_cash,
    market: doc.market,
    brief: brief === null || brief === undefined ? "" : String(brief),
    strategy: doc.strategy.name,
    strategyParams: scalars(doc.strategy.params),
    selector: doc.portfolio.selector?.name ?? "",
    selectorParams: scalars(doc.portfolio.selector?.params),
    allocation: doc.portfolio.allocation ?? "",
    allocationParams: scalars(doc.portfolio.params),
    riskPct,
    allowFractional: doc.risk.allow_fractional === true,
    webhookUrl: doc.notify.webhook_url ?? "",
    ntfyTopic: doc.notify.ntfy_topic ?? "",
    ntfyServer: doc.notify.ntfy_server ?? "",
  };
}

// Same component as before: keep its non-form params; a new one: form params only.
function merged(sameName: boolean, old: ParamMap | undefined, form: Record<string, ParamValue>) {
  return sameName ? { ...(old ?? {}), ...form } : { ...form };
}

export function toDoc(form: SettingsForm, original: SettingsDoc): SettingsDoc {
  // A JSON copy, not structuredClone: Alpine hands us a reactive Proxy, which
  // structuredClone refuses to clone.
  const doc = JSON.parse(JSON.stringify(original)) as SettingsDoc;
  doc.symbols = parseSymbols(form.symbols);
  doc.timeframe = form.timeframe;
  doc.poll_seconds = Number(form.poll_seconds);
  doc.initial_cash = Number(form.initial_cash);
  doc.market = form.market;
  doc.autopilot = { brief_minutes_before_open: form.brief.trim() === "" ? null : Number(form.brief) };
  doc.strategy = {
    name: form.strategy,
    params: merged(form.strategy === original.strategy.name, original.strategy.params, form.strategyParams),
  };
  const oldSelector = original.portfolio.selector;
  doc.portfolio.selector = form.selector
    ? { name: form.selector, params: merged(form.selector === oldSelector?.name, oldSelector?.params, form.selectorParams) }
    : null;
  doc.portfolio.allocation = form.allocation || null;
  doc.portfolio.params = form.allocation
    ? merged(form.allocation === original.portfolio.allocation, original.portfolio.params, form.allocationParams)
    : {};
  for (const key of PERCENT_FIELDS) {
    const value = fromPercent(form.riskPct[key] ?? "");
    doc.risk[key] = value === null && !NULLABLE.has(key) ? original.risk[key] ?? null : value;
  }
  doc.risk.allow_fractional = form.allowFractional;
  // A masked or blank secret goes back as sent: the server keeps the stored one.
  doc.notify = {
    webhook_url: form.webhookUrl.trim() || null,
    ntfy_topic: form.ntfyTopic.trim() || null,
    ntfy_server: form.ntfyServer.trim() || null,
  };
  return doc;
}
