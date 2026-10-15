// Today page: one big Refresh button. It asks the server to compute a fresh
// proposal (a background job), polls the job, then reloads the stored proposal
// and swaps in the server-rendered list, so the markup lives in one template.
// "Updated X ago" ticks locally from the proposal's timestamp. The watchlist
// chips are server-rendered too; an add or a remove posts, then reloads them
// and the proposal list (whose empty state names the list in use). The
// Discover card (./discover) adds names on its own and announces it with a
// `watchlist-changed` event, which reloads the same panes. The other way
// round, an edit here fires `watchlist-edited` on the window so Discover
// re-renders its rows ("on watchlist" / Add) to match.

import { changeWatchlist, getJob, getPartial, getProposal, refreshProposal } from "../api/client";
import type { WatchlistChange } from "../types";
import { dispatch, el, refs } from "../alpine";

export const WATCHLIST_EDITED = "watchlist-edited";

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

// What to ask before a remove. The server writes it on the chip: a held name
// says the autopilot sells it at its next pass (the list is the mandate).
export function removalQuestion(target: HTMLElement | null): string {
  const chip = target?.closest<HTMLElement>("[data-remove-symbol]");
  return chip?.dataset.removeConfirm || `Remove ${chip?.dataset.removeSymbol ?? ""}?`;
}

export function today() {
  return {
    state: "idle",
    error: "",
    createdAt: "",
    ago: "",
    newSymbol: "",
    notice: "",

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
      const target = event.target as HTMLElement | null;
      const change = removalFor(target);
      if (change && this.ask(removalQuestion(target))) await this.editWatchlist(change);
    },

    // A seam for tests; the browser's own confirmation dialog.
    ask(question: string): boolean {
      return window.confirm(question);
    },

    // True when the server accepted the edit; its refusal shows as the error.
    async editWatchlist(change: WatchlistChange): Promise<boolean> {
      this.error = "";
      this.notice = "";
      try {
        this.notice = (await changeWatchlist(change)).notice ?? "";
      } catch (err) {
        this.state = "error";
        this.error = err instanceof Error ? err.message : String(err);
        return false;
      }
      // Accepted: a pane that fails to reload shows its own error.
      dispatch(this, WATCHLIST_EDITED, change);
      await this.reloadPanes();
      return true;
    },

    // Also the handler for Discover's `watchlist-changed`, which nothing
    // awaits: a failed reload must land on the page, not in the console.
    async reloadPanes() {
      try {
        const panes = refs(this);
        panes.watchlist.innerHTML = await getPartial("/partials/watchlist");
        panes.list.innerHTML = await getPartial("/partials/proposal");
      } catch (err) {
        this.state = "error";
        this.error = err instanceof Error ? err.message : String(err);
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
