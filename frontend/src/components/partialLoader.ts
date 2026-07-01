// Fetches an HTML fragment and swaps it in, optionally polling on an interval.
// Keeps the server-rendered markup until the first fetch resolves (no flash).

import { getPartial } from "../api/client";
import { el, live } from "../alpine";
import { LIVE_TICK } from "../sse";

export function partialLoader(url: string) {
  return {
    html: "",
    async init() {
      this.html = el(this).innerHTML;
      await this.refresh();
      // Re-fetch on each SSE heartbeat (unless paused).
      window.addEventListener(LIVE_TICK, () => {
        if (live(this).enabled) {
          void this.refresh();
        }
      });
    },
    async refresh() {
      try {
        this.html = await getPartial(url);
      } catch (error) {
        console.error(error);
      }
    },
  };
}
