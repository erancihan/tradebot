// One Server-Sent Events stream drives the whole dashboard: it pushes the live
// account snapshot into the shared store and emits a `live:tick` window event
// that the chart/table components re-fetch on. EventSource reconnects on its own.

import type { LiveStore } from "./alpine";
import type { AccountView } from "./types";

export const LIVE_TICK = "live:tick";

export function startSse(store: LiveStore): void {
  const source = new EventSource("/sse/dashboard");
  source.addEventListener("account", (event) => {
    if (!store.enabled) {
      return; // paused: ignore until resumed
    }
    try {
      store.account = JSON.parse((event as MessageEvent).data) as AccountView;
    } catch {
      // ignore malformed payloads
    }
    store.stamp();
    store.tick += 1;
    window.dispatchEvent(new Event(LIVE_TICK));
  });
}
