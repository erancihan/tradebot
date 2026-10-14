// Autopilot page: three mode buttons, a status card and the trades waiting for
// approval. The markup is server-rendered (components/autopilot_panel.html);
// this component sends a command, then swaps the fresh panel in. Clicks are
// delegated from the section root and read data-* attributes, so swapped-in
// buttons work without re-binding.

import { commandAutopilot, getPartial } from "../api/client";
import { refs } from "../alpine";
import type { AutopilotCommand, AutopilotModeKey } from "../types";

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
  if (approve !== undefined) return { approve: ids(approve) };
  if (reject !== undefined) return { reject: ids(reject) };
  return null;
}

function ids(csv: string): number[] {
  return csv
    .split(",")
    .map((part) => Number.parseInt(part, 10))
    .filter((n) => Number.isFinite(n));
}

export function autopilot() {
  return {
    busy: false,
    error: "",

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
        await commandAutopilot(command);
        await this.reload();
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.busy = false;
      }
    },

    async reload() {
      refs(this).panel.innerHTML = await getPartial("/partials/autopilot");
    },
  };
}
