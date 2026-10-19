// Settings page: the file's version round-trips, so the server can refuse a
// save made from a page that never saw the file's latest edit.

import { settings } from "../src/components/settings";
import type { SettingsDoc } from "../src/types";
import { check, json, stubFetch } from "./harness";

const doc = {
  symbols: ["SPY"], timeframe: "1day", poll_seconds: 300, market: "us_equities",
  autopilot: { brief_minutes_before_open: null }, initial_cash: 10000,
  strategy: { name: "buy_and_hold", params: {} },
  portfolio: { selector: null, allocation: null, params: {}, overlays: [] },
  risk: {}, notify: { webhook_url: null, ntfy_topic: null, ntfy_server: null },
} as unknown as SettingsDoc;

function view(version: string) {
  return { settings: doc, mode: "paper", credentials_present: false, config_path: "config.yaml",
           config_exists: true, webhook_configured: false, ntfy_configured: false,
           choices: { markets: [], timeframes: [] }, notice: null, version };
}

const posted: Record<string, unknown>[] = [];
let next = "v2";
stubFetch((url, init) => {
  if (url.endsWith("/api/settings") && init?.method === "POST") {
    posted.push(JSON.parse(String(init.body)));
    const answer = view(next);
    next = "v3";
    return json(answer);
  }
  if (url.endsWith("/api/settings")) return json(view("v1"));
  if (url.endsWith("/api/stack")) return json({ selectors: [], allocators: [] });
  return json([]);
});

const page = settings();
await page.init();
check(page.version === "v1", `the page keeps the loaded version: ${page.version}`);
await page.save();
check(posted[0]?.version === "v1", `a save posts the version it loaded: ${JSON.stringify(posted[0])}`);
check(page.version === "v2", `after a save the page keeps the new version: ${page.version}`);
await page.save();
check(posted[1]?.version === "v2", "the next save posts the new version");
