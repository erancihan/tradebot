// Today page: one big Refresh button. It asks the server to compute a fresh
// proposal (a background job), polls the job, then reloads the stored proposal
// and swaps in the server-rendered list, so the markup lives in one template.
// "Updated X ago" ticks locally from the proposal's timestamp. The watchlist
// chips are server-rendered too; an add or a remove posts, then reloads them
// and the proposal list (whose empty state names the list in use).

import { changeWatchlist, getJob, getPartial, getProposal, refreshProposal } from "../api/client";
import type { WatchlistChange } from "../types";
import { el, refs } from "../alpine";

const POLL_MS = 700;
const TICK_MS = 30_000;

export function ago(createdAt: string, now: number = Date.now()): string {
  if (!createdAt) return "";
  const seconds = Math.max(0, Math.round((now - Date.parse(createdAt)) / 1000));
  if (seconds < 60) return "updated just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `updated ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `updated ${hours} h ago`;
  return `updated ${Math.round(hours / 24)} days ago`;
}

// The remove command a tapped chip button asks for, or null.
export function removalFor(target: HTMLElement | null): WatchlistChange | null {
  const symbol = target?.closest<HTMLElement>("[data-remove-symbol]")?.dataset.removeSymbol;
  return symbol ? { remove: [symbol] } : null;
}

export function today() {
  return {
    state: "idle",
    error: "",
    createdAt: "",
    ago: "",
    newSymbol: "",

    init() {
      this.createdAt = el(this).dataset.createdAt ?? "";
      this.tick();
      window.setInterval(() => this.tick(), TICK_MS);
    },

    tick() {
      this.ago = ago(this.createdAt);
    },

    async refresh() {
      this.state = "running";
      this.error = "";
      try {
        const { job_id } = await refreshProposal();
        await this.waitFor(job_id);
        const envelope = await getProposal();
        this.createdAt = envelope.proposal?.created_at ?? "";
        refs(this).list.innerHTML = await getPartial("/partials/proposal");
        this.tick();
        this.state = "done";
      } catch (err) {
        this.state = "error";
        this.error = err instanceof Error ? err.message : String(err);
      }
    },

    async addSymbol() {
      const symbol = this.newSymbol.trim().toUpperCase();
      if (!symbol) return;
      if (await this.editWatchlist({ add: [symbol] })) this.newSymbol = "";
    },

    async onWatchlistClick(event: Event) {
      const change = removalFor(event.target as HTMLElement | null);
      if (change) await this.editWatchlist(change);
    },

    // True when the server accepted the edit; its refusal shows as the error.
    async editWatchlist(change: WatchlistChange): Promise<boolean> {
      this.error = "";
      try {
        await changeWatchlist(change);
        const panes = refs(this);
        panes.watchlist.innerHTML = await getPartial("/partials/watchlist");
        panes.list.innerHTML = await getPartial("/partials/proposal");
        return true;
      } catch (err) {
        this.state = "error";
        this.error = err instanceof Error ? err.message : String(err);
        return false;
      }
    },

    // Resolves when the job is done; rejects with the server's message on error.
    async waitFor(jobId: string): Promise<void> {
      for (;;) {
        const job = await getJob(jobId);
        if (job.state === "done") return;
        if (job.state === "error") throw new Error(job.error ?? "refresh failed");
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      }
    },
  };
}
