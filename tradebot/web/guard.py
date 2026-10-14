"""Same-origin guard: state-changing requests must carry a custom header.

A cross-origin HTML form or a CORS "simple" request cannot set a custom header,
and this server sends no CORS headers, so a browser refuses to let another
origin add one. Requiring ``X-Requested-With: tradebot`` on every mutating
method therefore blocks CSRF without tokens, cookies-to-forms plumbing or
per-page state. The TypeScript client sets it centrally (``api/client.ts``).
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

HEADER_NAME = "X-Requested-With"
HEADER_VALUE = "tradebot"
#: What tests (and any non-browser caller) send with a mutating request.
POST_HEADERS = {HEADER_NAME: HEADER_VALUE}

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class SameOriginGuard:
    """Pure ASGI, not ``BaseHTTPMiddleware``, so SSE streams pass untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in MUTATING_METHODS \
                and not _has_header(scope):
            await _forbid(send)
            return
        await self.app(scope, receive, send)


def _has_header(scope: Scope) -> bool:
    wanted = HEADER_NAME.lower().encode()
    return any(name == wanted and value.decode("latin-1") == HEADER_VALUE
               for name, value in scope.get("headers", []))


async def _forbid(send: Send) -> None:
    body = json.dumps({"detail": f"missing {HEADER_NAME} header"}).encode()
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
