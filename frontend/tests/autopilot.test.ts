// The Autopilot page's taps: an approval carries the sizes the page showed,
// so the server can refuse a line re-sized since (it buys what was on screen).

import { commandFor, shown } from "../src/components/autopilot";
import { check } from "./harness";

function button(dataset: Record<string, string>): HTMLElement {
  const el = { dataset, closest: () => el };
  return el as unknown as HTMLElement;
}

const all = commandFor(button({ approve: "7,8", seen: "7:3500.5,8:1200" }));
check(JSON.stringify(all) === JSON.stringify({ approve: [7, 8], seen: { "7": 3500.5, "8": 1200 } }),
      `approve all carries what it showed: ${JSON.stringify(all)}`);

const one = commandFor(button({ approve: "7", seen: "7:-250.25" }));
check(JSON.stringify(one) === JSON.stringify({ approve: [7], seen: { "7": -250.25 } }),
      `one line carries its notional: ${JSON.stringify(one)}`);

const old = commandFor(button({ approve: "7" }));
check(JSON.stringify(old) === JSON.stringify({ approve: [7] }), "no data-seen: no seen key");

check(shown("7:abc") === null, "an unreadable size is no size at all");
check(shown("") === null && shown(undefined) === null, "absent is null");

const reject = commandFor(button({ reject: "7", seen: "7:1" }));
check(JSON.stringify(reject) === JSON.stringify({ reject: [7] }), "a rejection needs no sizes");
