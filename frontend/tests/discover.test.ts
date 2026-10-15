// Discover: a search swaps in the rows, a failed job shows its error, and an
// Add posts to /api/discover/add with the guard header, re-renders the rows and
// tells the Today page.

import { additionFor, discover } from "../src/components/discover";
import { check, json, sleep, stubFetch } from "./harness";

const posts: { url: string; body: string; guard: string | null }[] = [];
let jobState = "done";
let partial = "<li data-discover-row=\"AAA\">AAA</li>";

stubFetch((url, init) => {
  if (init?.method === "POST") {
    const headers = new Headers(init.headers);
    posts.push({ url, body: String(init.body), guard: headers.get("X-Requested-With") });
  }
  if (url === "/api/discover/run") return json({ job_id: "d1" });
  if (url === "/api/jobs/d1") {
    return json({ id: "d1", kind: "discover", state: jobState, error: "no cached daily bars to search" });
  }
  if (url === "/partials/discover") return new Response(partial);
  if (url === "/api/discover/add") {
    return json({ symbols: ["AAA"], source: "watchlist", notice: "The autopilot loop was stopped" });
  }
  return json({}, 404);
});

function mount() {
  const page = discover();
  const rows = { innerHTML: "" };
  const events: string[] = [];
  Object.assign(page, {
    $refs: { rows },
    $dispatch: (name: string) => events.push(name),
  });
  return { page, rows, events };
}

// A search that completes swaps in the server's rows.
{
  const { page, rows } = mount();
  await page.find();
  check(page.state === "done", `state is "done", got "${page.state}"`);
  check(rows.innerHTML.includes("data-discover-row"), "the rows were swapped in");
  check(posts[0]?.url === "/api/discover/run" && posts[0].guard === "tradebot",
        "the run was posted with the guard header");
}

// A failed job ends in "error" with the server's message, rows untouched.
{
  jobState = "error";
  const { page, rows } = mount();
  await page.find();
  check(page.state === "error", `state is "error", got "${page.state}"`);
  check(page.error.includes("no cached daily bars"), `the error names the failure: "${page.error}"`);
  check(rows.innerHTML === "", "no rows on a failed search");
  jobState = "done";
}

// Add posts {symbol}, re-renders the rows and announces the change.
{
  posts.length = 0;
  partial = "<li data-discover-row=\"AAA\"><span data-on-watchlist>on watchlist</span></li>";
  const { page, rows, events } = mount();
  await page.add("AAA");
  await sleep(0);
  check(posts.length === 1 && posts[0].url === "/api/discover/add", "one add post");
  check(JSON.parse(posts[0].body).symbol === "AAA", `posted ${posts[0].body}`);
  check(posts[0].guard === "tradebot", "the add carries the guard header");
  check(rows.innerHTML.includes("on watchlist"), "the row flipped to on watchlist");
  check(events.includes("watchlist-changed"), "the Today panes were told");
  check(page.notice.includes("autopilot"), "the autopilot notice is shown");
  check(page.adding === "", "the button is released");
}

// Only an Add button (or something inside one) names a symbol.
{
  const button = { closest: () => ({ dataset: { addSymbol: "BBB" } }) } as unknown as HTMLElement;
  const other = { closest: () => null } as unknown as HTMLElement;
  check(additionFor(button) === "BBB", "an Add button names its symbol");
  check(additionFor(other) === null && additionFor(null) === null, "anything else is ignored");
}
