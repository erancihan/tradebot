// Typed wrappers around the JSON endpoints. The only place that knows URLs.

import type {
  AccountView,
  ArenaRunDetail,
  AutopilotCommand,
  AutopilotView,
  CacheEntry,
  CandleSeries,
  EquitySeries,
  JobRequest,
  JobView,
  NotifyTestResult,
  OrderRow,
  ProposalEnvelope,
  SeasonDetail,
  SettingsDoc,
  SettingsView,
  StackSpecs,
  StrategySpec,
  WatchlistChange,
  WatchlistView,
  WhatIfRequest,
} from "../types";

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}): ${url}`);
  }
  return (await response.json()) as T;
}

// The server refuses any mutating request without this header (web/guard.py):
// a cross-origin form cannot set it, which is what makes it a CSRF guard.
const SAME_ORIGIN_HEADER = { "X-Requested-With": "tradebot" } as const;

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...SAME_ORIGIN_HEADER,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((data: { detail?: unknown }) => detailText(data.detail))
      .catch(() => "");
    throw new Error(detail || `Request failed (${response.status}): ${url}`);
  }
  return (await response.json()) as T;
}

interface ValidationIssue {
  loc?: unknown[];
  msg?: unknown;
}

// The server's reason for a refusal. A 400 carries a string ("not a symbol:
// 1X"); FastAPI's 422 carries a list of {loc, msg}, shown as "field: msg"
// with the field taken from the end of `loc` (its head is just "body").
function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "";
  return detail
    .map((issue: ValidationIssue) => {
      const msg = typeof issue?.msg === "string" ? issue.msg : "";
      const loc = Array.isArray(issue?.loc) ? issue.loc : [];
      const field = loc.length > 1 ? loc.slice(1).join(".") : loc.join(".");
      return field && msg ? `${field}: ${msg}` : msg;
    })
    .filter((text) => text.length > 0)
    .join("; ");
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

// One page of History's timeline: the fragment, and the next page's URL from
// the `X-History-Next` header ("" on the last page).
export async function getHistoryPage(url: string): Promise<{ html: string; next: string }> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Partial failed (${response.status}): ${url}`);
  }
  return { html: await response.text(), next: response.headers.get("X-History-Next") ?? "" };
}

export function getStrategies(): Promise<StrategySpec[]> {
  return getJson<StrategySpec[]>("/api/strategies");
}

export function getCache(): Promise<CacheEntry[]> {
  return getJson<CacheEntry[]>("/api/cache");
}

export function submitJob(body: JobRequest): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/jobs", body);
}

export function getJob(id: string): Promise<JobView> {
  return getJson<JobView>(`/api/jobs/${id}`);
}

const POLL_MS = 500;

// Polls a job until it settles and returns it, "done" or "error". A failing
// request throws, so a caller that awaits this inside its try surfaces the
// failure instead of leaving a run spinning forever.
export async function waitForJob(id: string, intervalMs = POLL_MS): Promise<JobView> {
  for (;;) {
    const job = await getJob(id);
    if (job.state === "done" || job.state === "error") return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function getProposal(): Promise<ProposalEnvelope> {
  return getJson<ProposalEnvelope>("/api/proposal");
}

export function refreshProposal(): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/proposal/refresh", {});
}

export function submitWhatIf(body: WhatIfRequest): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/whatif", body);
}

export function submitWhatIfCompare(body: WhatIfRequest): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/whatif/compare", body);
}

export function getAutopilot(): Promise<AutopilotView> {
  return getJson<AutopilotView>("/api/autopilot");
}

export function commandAutopilot(body: AutopilotCommand): Promise<AutopilotView> {
  return postJson<AutopilotView>("/api/autopilot", body);
}

export function sendTestAlert(): Promise<NotifyTestResult> {
  return postJson<NotifyTestResult>("/api/notify/test", {});
}

export function changeWatchlist(body: WatchlistChange): Promise<WatchlistView> {
  return postJson<WatchlistView>("/api/watchlist", body);
}

export function runDiscover(): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>("/api/discover/run", {});
}

export function getSettings(): Promise<SettingsView> {
  return getJson<SettingsView>("/api/settings");
}

export function saveSettings(body: SettingsDoc): Promise<SettingsView> {
  return postJson<SettingsView>("/api/settings", body);
}

export function getStack(): Promise<StackSpecs> {
  return getJson<StackSpecs>("/api/stack");
}
