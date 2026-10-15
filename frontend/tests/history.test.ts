// History's "Show more": appends the next page, follows the header's cursor,
// stops on the last page, and pauses the poll once older pages are shown.

import { history } from "../src/components/history";
import { check, stubFetch } from "./harness";

const pages: Record<string, { html: string; next: string }> = {
  "/partials/history?before_order=5": { html: "<li>p2</li>", next: "/partials/history?before_order=2" },
  "/partials/history?before_order=2": { html: "<li>p3</li>", next: "" },
  "/partials/history": { html: "<li>fresh</li>", next: "/partials/history?before_order=9" },
};
const asked: string[] = [];
stubFetch((url) => {
  asked.push(url);
  const page = pages[url];
  if (!page) return new Response("nope", { status: 500 });
  return new Response(page.html, { headers: { "X-History-Next": page.next } });
});

// A stand-in for the <ol x-ref="list">: enough of the DOM for the component.
const list = {
  innerHTML: "<li>p1</li>",
  insertAdjacentHTML(where: string, html: string) {
    check(where === "beforeend", `appends at the end, not ${where}`);
    this.innerHTML += html;
  },
};
const page = Object.assign(history(), { $refs: { list } });
page.next = "/partials/history?before_order=5";

await page.more();
check(list.innerHTML === "<li>p1</li><li>p2</li>", `second page appended: ${list.innerHTML}`);
check(page.next === "/partials/history?before_order=2", `cursor advanced: ${page.next}`);
check(page.pages === 2, `two pages shown, got ${page.pages}`);

await page.poll();
check(!asked.includes("/partials/history"), "no poll once an older page is shown");

await page.more();
check(list.innerHTML.endsWith("<li>p3</li>"), "third page appended");
check(page.next === "", "the last page clears the button");
const before = asked.length;
await page.more();
check(asked.length === before, "no fetch after the last page");

// A failing page reports the error and keeps the cursor for a retry.
const broken = Object.assign(history(), { $refs: { list } });
broken.next = "/partials/history?before_order=404";
await broken.more();
check(broken.error.includes("500"), `the error names the failure: "${broken.error}"`);
check(broken.next === "/partials/history?before_order=404", "cursor kept for a retry");
check(!broken.busy, "not stuck busy");

// On the first page the poll swaps in the newest page and its cursor.
const fresh = Object.assign(history(), { $refs: { list } });
await fresh.poll();
check(list.innerHTML === "<li>fresh</li>", `newest page swapped in: ${list.innerHTML}`);
check(fresh.next === "/partials/history?before_order=9", `cursor from the poll: ${fresh.next}`);
