// Typed wrappers around the JSON endpoints. The only place that knows URLs.

import type {
  AccountView,
  ArenaRunDetail,
  CandleSeries,
  EquitySeries,
  JobRequest,
  JobView,
  OrderRow,
  SeasonDetail,
} from "../types";

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}): ${url}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}): ${url}`);
  }
  return (await response.json()) as T;
}

export function getEquity(mode?: string): Promise<EquitySeries> {
  const params = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return getJson<EquitySeries>(`/api/equity${params}`);
}

export function getOrders(mode?: string): Promise<OrderRow[]> {
  const params = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return getJson<OrderRow[]>(`/api/orders${params}`);
}

export function getBars(symbol: string): Promise<CandleSeries> {
  return getJson<CandleSeries>(`/api/bars?symbol=${encodeURIComponent(symbol)}`);
}

export function getAccount(): Promise<AccountView> {
  return getJson<AccountView>("/api/account");
}

export function getArenaRun(runId: number): Promise<ArenaRunDetail> {
  return getJson<ArenaRunDetail>(`/api/arena/runs/${runId}`);
}

export function getSeasonDetail(seasonId: number): Promise<SeasonDetail> {
  return getJson<SeasonDetail>(`/api/seasons/${seasonId}`);
}

export async function getPartial(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Partial failed (${response.status}): ${url}`);
  }
  return response.text();
}

export function submitJob(body: JobRequest): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/jobs", body);
}

export function getJob(id: string): Promise<JobView> {
  return getJson<JobView>(`/api/jobs/${id}`);
}
