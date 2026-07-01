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

export interface JobRequest {
  kind: string;
  strategy: string;
  periods: number;
  seed: number;
  initial_cash: number;
  params: Record<string, number>;
}

export interface JobView {
  id: string;
  kind: string;
  state: string;
  summary?: Record<string, number | string> | null;
  equity?: EquityCurve | null;
  error?: string | null;
}
