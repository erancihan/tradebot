// A few helpers for the Node-run behaviour tests (see ../test.mjs).

export function check(condition: boolean, message: string): void {
  if (!condition) throw new Error(`assertion failed: ${message}`);
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type Responder = (url: string, init?: RequestInit) => Response;

// Replace `fetch` for the test: every call goes to `respond`.
export function stubFetch(respond: Responder): void {
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) =>
    respond(String(input), init)) as typeof fetch;
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
