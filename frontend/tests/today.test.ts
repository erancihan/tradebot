// Today and Discover keep each other current: a watchlist edit on Today
// announces itself so the Discover card reloads its rows, and a pane reload
// that fails (Discover's add triggers one nothing awaits) shows on the page.

import { discover } from "../src/components/discover";
import { WATCHLIST_EDITED, today } from "../src/components/today";
import { check, json, stubFetch } from "./harness";

let partialsDown = false;
let discoverRows = "<li data-discover-row=\"AAA\"><button data-add-symbol=\"AAA\">Add</button></li>";

stubFetch((url) => {
  if (url === "/api/watchlist") return json({ symbols: ["AAA"], source: "watchlist" });
  if (partialsDown && url.startsWith("/partials/")) return json({ detail: "down" }, 500);
  if (url === "/partials/discover") return new Response(discoverRows);
  if (url.startsWith("/partials/")) return new Response(`<p>${url}</p>`);
  return json({}, 404);
});

function mountToday() {
  const page = today();
  const panes = { watchlist: { innerHTML: "" }, list: { innerHTML: "" } };
  const events: string[] = [];
  Object.assign(page, {
    $refs: panes,
    $dispatch: (name: string) => events.push(name),
  });
  return { page, panes, events };
}

// An accepted edit reloads the panes and tells Discover.
{
  const { page, panes, events } = mountToday();
  check(await page.editWatchlist({ add: ["AAA"] }), "the edit was accepted");
  check(events.includes(WATCHLIST_EDITED), `Discover was told: ${events.join(",")}`);
  check(panes.watchlist.innerHTML.includes("/partials/watchlist"), "the watchlist reloaded");
  check(page.error === "", `no error: "${page.error}"`);
}

// Discover hears it and re-renders its rows: AAA now reads "on watchlist".
{
  const card = discover();
  const rows = { innerHTML: "stale" };
  Object.assign(card, { $refs: { rows } });
  discoverRows = "<li data-discover-row=\"AAA\"><span data-on-watchlist>on watchlist</span></li>";
  await card.onWatchlistEdited();
  check(rows.innerHTML.includes("on watchlist"), `rows reloaded: ${rows.innerHTML}`);
}

// A failed pane reload sets the page error instead of rejecting unheard.
{
  partialsDown = true;
  const { page } = mountToday();
  await page.reloadPanes();
  check(page.state === "error" && page.error !== "", `the page shows it: "${page.error}"`);

  const card = discover();
  Object.assign(card, { $refs: { rows: { innerHTML: "" } } });
  await card.onWatchlistEdited();
  check(card.error !== "", "the Discover card shows its reload failure");
  partialsDown = false;
}
