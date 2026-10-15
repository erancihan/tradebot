// Today's Discover card: "what else could I buy?". "Find candidates" runs the
// server's `discover` job (momentum over a screened pool, minus what is watched
// or held), polls it, then swaps in the server-rendered rows. A row's Add
// posts to /api/discover/add (an empty watchlist is first seeded with the
// active symbols, so they stay), re-renders the rows (that row now reads "on
// watchlist") and fires `watchlist-changed` so the Today panes reload too.
// A watchlist edit on the Today page fires `watchlist-edited` on the window,
// and the card reloads its rows (`onWatchlistEdited`) so Add matches the list.

import { addFromDiscover, getPartial, runDiscover, waitForJob } from "../api/client";
import { dispatch, refs } from "../alpine";

// The symbol a tapped Add button asks for, or null.
export function additionFor(target: HTMLElement | null): string | null {
  return target?.closest<HTMLElement>("[data-add-symbol]")?.dataset.addSymbol ?? null;
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function discover() {
  return {
    state: "idle", // idle | running | done | error
    error: "",
    notice: "",
    adding: "",

    async find() {
      this.state = "running";
      this.error = "";
      this.notice = "";
      try {
        const { job_id } = await runDiscover();
        const job = await waitForJob(job_id);
        if (job.state === "error") throw new Error(job.error ?? "the search failed");
        await this.reloadRows();
        this.state = "done";
      } catch (err) {
        this.state = "error";
        this.error = message(err);
      }
    },

    async onRowClick(event: Event) {
      const symbol = additionFor(event.target as HTMLElement | null);
      if (symbol) await this.add(symbol);
    },

    // Adding stops a running autopilot (as any watchlist edit does): the
    // server says so in `notice`, shown on the card.
    async add(symbol: string) {
      if (this.adding) return;
      this.adding = symbol;
      this.error = "";
      try {
        this.notice = (await addFromDiscover(symbol)).notice ?? "";
        await this.reloadRows();
        dispatch(this, "watchlist-changed", { symbol });
      } catch (err) {
        this.error = message(err);
      } finally {
        this.adding = "";
      }
    },

    async reloadRows() {
      refs(this).rows.innerHTML = await getPartial("/partials/discover");
    },

    async onWatchlistEdited() {
      try {
        await this.reloadRows();
      } catch (err) {
        this.error = message(err);
      }
    },
  };
}
