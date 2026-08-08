// Shapes mirror the Pydantic models in tradebot/web/schemas.py.

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
  provenance?: Provenance | null;
  error?: string | null;
}
