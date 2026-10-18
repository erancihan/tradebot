// Autopilot page: three mode buttons, a status card and the trades waiting for
// approval. The markup is server-rendered (components/autopilot_panel.html);
// this component sends a command, then swaps the fresh panel in. Clicks are
// delegated from the section root and read data-* attributes, so swapped-in
// buttons work without re-binding.

import { commandAutopilot, getPartial, sendTestAlert } from "../api/client";
import { refs } from "../alpine";
import type { AutopilotCommand, AutopilotModeKey, NotifyTestResult } from "../types";

const POLL_MS = 10_000;
const MODES: readonly string[] = ["off", "approve", "auto"];

// The command a tapped element asks for, or null when it is not a control.
export function commandFor(target: HTMLElement | null): AutopilotCommand | null {
  const button = target?.closest<HTMLElement>("[data-mode],[data-approve],[data-reject]");
  if (!button) return null;
  const { mode, approve, reject } = button.dataset;
  if (mode !== undefined && MODES.includes(mode)) {
    return { mode: mode as AutopilotModeKey };
  }
  if (approve !== undefined) {
    const seen = shown(button.dataset.seen);
    return seen ? { approve: ids(approve), seen } : { approve: ids(approve) };
  }
  if (reject !== undefined) return { reject: ids(reject) };
  return null;
}

// "id:notional,..." (data-seen) as { id: notional }, or null when absent or
// unreadable: the server then cannot hold the tap to what the page showed.
export function shown(csv: string | undefined): Record<string, number> | null {
  if (!csv) return null;
  const out: Record<string, number> = {};
  for (const pair of csv.split(",")) {
    const [id, notional] = pair.split(":");
    const value = Number.parseFloat(notional ?? "");
    if (!id || !Number.isFinite(value)) return null;
    out[id.trim()] = value;
  }
  return out;
}

function ids(csv: string): number[] {
  return csv
    .split(",")
    .map((part) => Number.parseInt(part, 10))
    .filter((n) => Number.isFinite(n));
}

// What the test-alert button reports back, in one line.
export function alertSummary(result: NotifyTestResult): string {
  const remote = result.channels.filter((c) => c !== "log");
  if (remote.length === 0) return "Only the log is configured: set notify.ntfy_topic in the config.";
  if (result.sent) return `Sent through ${remote.join(" and ")}.`;
  return `Not delivered through ${result.failed.join(" and ")}; check the server log.`;
}

export function autopilot() {
  return {
    busy: false,
    error: "",
    alert: "",

    init() {
      window.setInterval(() => {
        if (!this.busy) void this.reload();
      }, POLL_MS);
    },

    async onClick(event: Event) {
      const command = commandFor(event.target as HTMLElement | null);
      if (!command || this.busy) return;
      this.busy = true;
      this.error = "";
      try {
        const view = await commandAutopilot(command);
        this.error = view.notice ?? "";
        await this.reload();
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.busy = false;
      }
    },

    async testAlert() {
      this.alert = "Sending…";
      try {
        this.alert = alertSummary(await sendTestAlert());
      } catch (err) {
        this.alert = err instanceof Error ? err.message : String(err);
      }
    },

    async reload() {
      refs(this).panel.innerHTML = await getPartial("/partials/autopilot");
    },
  };
}
