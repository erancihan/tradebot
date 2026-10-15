// A refused request shows the server's reason, including FastAPI's 422 list.

import { submitWhatIf } from "../src/api/client";
import type { WhatIfRequest } from "../src/types";
import { check, json, stubFetch } from "./harness";

async function messageFor(response: Response): Promise<string> {
  stubFetch(() => response);
  try {
    await submitWhatIf({} as WhatIfRequest);
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
  throw new Error("the request was expected to fail");
}

const invalid = await messageFor(json({
  detail: [
    { type: "missing", loc: ["body", "symbols"], msg: "Field required" },
    { type: "greater_than", loc: ["body", "initial_cash"], msg: "Input should be greater than 0" },
  ],
}, 422));
check(invalid === "symbols: Field required; initial_cash: Input should be greater than 0",
      `422 lists each field's problem, got "${invalid}"`);

const refused = await messageFor(json({ detail: "not a symbol: 1X" }, 400));
check(refused === "not a symbol: 1X", `a string detail is shown as is, got "${refused}"`);

const opaque = await messageFor(new Response("oops", { status: 500 }));
check(opaque === "Request failed (500): /api/whatif", `no detail falls back, got "${opaque}"`);
