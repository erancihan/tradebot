// A What-if run whose job poll fails must end in "error", not spin forever.

import { whatIf } from "../src/components/whatif";
import { check, json, sleep, stubFetch } from "./harness";

let polls = 0;
stubFetch((url) => {
  if (url === "/api/whatif") return json({ job_id: "j1" });
  if (url === "/api/jobs/j1") {
    polls += 1;
    // The first poll finds the job running; the next one fails.
    return polls === 1 ? json({ id: "j1", state: "running" }) : json({}, 500);
  }
  return json({}, 404);
});

const page = whatIf();
await page.submit();
await sleep(50);          // let anything still scheduled settle
check(polls === 2, `polled twice, got ${polls}`);
check(page.state === "error", `state is "error", got "${page.state}"`);
check(page.error.includes("500"), `the error names the failure: "${page.error}"`);
