// Shapes mirror the Pydantic models in tradebot/web/schemas/.

export interface EquityPoint {
  ts: string;
  equity: number;
  cash: number;
  mode: string;
}

export interface EquitySeries {
  mode: string | null;
  points: EquityPoint[];
}

export interface OrderRow {
  ts: string;
  symbol: string;
  side: string;
  qty: number;
  mode: string;
}

export interface Candle {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleSeries {
  symbol: string;
  candles: Candle[];
}

export interface PositionView {
  symbol: string;
  qty: number;
  avg_price: number;
}

export interface AccountView {
  source: string;
  equity: number | null;
  cash: number | null;
  buying_power: number | null;
  market_open: boolean | null;
  positions: PositionView[];
}

export interface SeasonCurve {
  name: string;
  steps: number[];
  total_return: number[];
}

export interface SeasonStanding {
  rank: number;
  name: string;
  total_return: number;
  score: number | null;
  equity: number;
}

export interface SeasonDetail {
  id: number;
  name: string;
  metric: string;
  latest: SeasonStanding[];
  curves: SeasonCurve[];
}

export interface ArenaCurve {
  name: string;
  index: string[];
  equity: number[];
}

export interface ArenaRunDetail {
  id: number;
  scenario: string;
  metric: string;
  curves: ArenaCurve[];
}

export interface EquityCurve {
  index: string[];
  equity: number[];
}

export interface StrategyParam {
  name: string;
  type: string; // "int" | "float" | "bool" | "str"
  default: number | boolean | string;
}

export interface StrategySpec {
  name: string;
  params: StrategyParam[];
}

export interface CacheWindow {
  start: string | null;
  end: string | null;
}

export interface CacheEntry {
  symbol: string;
  timeframe: string;
  bars: number;
  first: string;
  last: string;
  coverage: CacheWindow[];
}

export interface Provenance {
  source: string; // "synthetic" | "real"
  symbol: string;
  bars: number;
  start: string;
  end: string;
  note: string;
  seed?: number;
  timeframe?: string;
}

export interface JobRequest {
  kind: string;
  strategy: string;
  source: string;
  periods: number;
  seed: number;
  symbol?: string;
  timeframe?: string;
  start?: string;
  end?: string;
  initial_cash: number;
  params: Record<string, number | boolean | string>;
}

export interface JobView {
  id: string;
  kind: string;
  state: string;
  summary?: Record<string, number | string> | null;
  equity?: EquityCurve | null;
  benchmark?: EquityCurve | null; // what-if only
  compare?: WhatIfCompare | null; // whatif_compare only
  provenance?: Provenance | null;
  error?: string | null;
}

// Today page: the latest stored proposal (see /api/proposal).
export interface ProposalLine {
  id: number;
  symbol: string;
  action: string; // "buy" | "sell" | "hold"
  target: number;
  current_qty: number;
  desired_qty: number;
  order_qty: number;
  price: number;
  notional: number;
  weight?: number | null;
  reason: string;
  status: string;
}

export interface ProposalView {
  id: number;
  created_at: string;
  age_seconds: number;
  mode: string;
  equity: number;
  cash: number;
  account_label: string;
  provenance: Record<string, unknown>;
  lines: ProposalLine[];
}

export interface ProposalEnvelope {
  configured: boolean;
  config_hint?: string | null;
  symbols: string[];
  symbol_source: string; // "watchlist" | "config"
  proposal?: ProposalView | null;
}

// GET/POST /api/watchlist: the active list and where it came from.
export interface WatchlistView {
  symbols: string[];
  source: string; // "watchlist" | "config"
  notice?: string; // set when the edit stopped a running autopilot
}

export type WatchlistChange = { add: string[] } | { remove: string[] };

export interface WhatIfRequest {
  symbols: string[];
  source: string; // "real" | "synthetic"
  start?: string;
  end?: string;
  initial_cash: number;
  monthly_contribution: number;
  strategy?: string;
  params?: Record<string, number | boolean | string>;
  allocation?: string;
  selector?: string;
  selector_params?: Record<string, number>;
}

// One ranked line of a strategy comparison (see /api/whatif/compare).
export interface CompareRow {
  name: string;
  final_value: number;
  gain: number;
  cagr: number;
  max_drawdown: number;
  vs_benchmark_pct: number;
  benchmark?: boolean; // the equal-weight buy-and-hold row
}

export interface WhatIfCompare {
  rows: CompareRow[]; // best final value first, benchmark not included
  benchmark: CompareRow;
  curves: Record<string, EquityCurve>; // the top five plus "benchmark"
  errors: { name: string; error: string }[];
  skipped: { name: string; reason: string }[];
  plan_strategy: string;
}

export interface WhatIfPresetRequest {
  symbols: string[];
  source: string;
  start: string | null;
  end: string | null;
  initial_cash: number;
  monthly_contribution: number;
  strategy: string;
  params: Record<string, number | boolean | string>;
  allocation: string;
  selector: string | null;
  selector_params: Record<string, number>;
}

export interface WhatIfPreset {
  name: string;
  description: string;
  request: WhatIfPresetRequest;
}

export type AutopilotModeKey = "off" | "approve" | "auto";

// Exactly one key per command: a mode switch, or line ids to approve/reject.
export type AutopilotCommand =
  | { mode: AutopilotModeKey }
  | { approve: number[] }
  | { reject: number[] };

export interface AutopilotState {
  mode: AutopilotModeKey;
  mode_label: string;
  running: boolean;
  account: string; // "paper" | "dry_run"
  started_at?: string | null;
  last_pass_at?: string | null;
  next_pass_at?: string | null;
  last_error?: string | null;
  pending: number;
}

export interface AutopilotView {
  state: AutopilotState;
  modes: { key: AutopilotModeKey; label: string }[];
  pending: ProposalLine[];
  notice?: string | null;
}

// POST /api/notify/test: every configured channel, and the ones that refused.
export interface NotifyTestResult {
  sent: boolean;
  channels: string[];
  failed: string[];
}

// GET/POST /api/settings: the editable part of config.yaml, in its YAML shape.
export type ParamValue = number | boolean | string;
export type ParamMap = Record<string, unknown>;

export interface NamedParams {
  name: string;
  params?: ParamMap;
}

export interface SettingsDoc {
  symbols: string[];
  timeframe: string;
  poll_seconds: number;
  initial_cash: number;
  market: string;
  autopilot: { brief_minutes_before_open: number | null };
  strategy: NamedParams;
  portfolio: {
    selector: NamedParams | null;
    allocation: string | null;
    params: ParamMap;
    overlays: NamedParams[];
  };
  risk: Record<string, number | boolean | null>;
  notify: { webhook_url: string | null; ntfy_topic: string | null; ntfy_server: string | null };
}

export interface SettingsView {
  settings: SettingsDoc;
  mode: string;
  credentials_present: boolean;
  config_path: string;
  config_exists: boolean;
  webhook_configured: boolean;
  ntfy_configured: boolean;
  choices: { markets: string[]; timeframes: string[] };
  notice: string | null;
}

// GET /api/stack: selectors and allocators a form can pick, with their params.
export interface StackSpecs {
  selectors: StrategySpec[];
  allocators: StrategySpec[];
}
