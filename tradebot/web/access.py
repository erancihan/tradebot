"""Optional access token, for reaching the dashboard over a network.

Off unless a token is configured (``TRADEBOT_WEB_TOKEN`` / ``--token``): on
localhost the machine's login is the access control. With one set, every
request needs either the session cookie that ``/login?token=...`` issues or an
``Authorization: Bearer <token>`` header. The cookie carries an HMAC of the
token, not the token, so a leaked cookie jar does not leak the secret that
mints new sessions; changing the token invalidates every cookie at once.
"""

from __future__ import annotations

import hashlib
import hmac

from starlette.requests import HTTPConnection
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE_NAME = "tradebot_session"
#: Assets a browser fetches before (or without) the cookie: the login page's
#: own styling, the PWA manifest and icons the home-screen shortcut needs.
OPEN_PREFIXES = ("/app/", "/static/")
LOGIN_PATH = "/login"
#: A year: the point is to log a phone in once, then use the home-screen icon.
COOKIE_MAX_AGE = 365 * 24 * 3600

_ASK_FOR_LOGIN = """<!doctype html><meta charset="utf-8">
<title>tradebot: sign in</title>
<p>This dashboard needs its access token.</p>
<p>Open <code>/login?token=&lt;your TRADEBOT_WEB_TOKEN&gt;</code> once in this browser.</p>
"""
_WRONG_TOKEN = """<!doctype html><meta charset="utf-8">
<title>tradebot: wrong token</title>
<p>That token is not the one this dashboard was started with.</p>
"""


def session_value(token: str) -> str:
    """The cookie value for ``token``: keyed by it, so it cannot be forged."""
    return hmac.new(token.encode(), b"tradebot-session-v1", hashlib.sha256).hexdigest()


class AccessToken:
    """Pure ASGI so the SSE stream is checked once, then streamed untouched."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token
        self.session = session_value(token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or _is_open(scope["path"]):
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        if scope["type"] == "http" and scope["path"] == LOGIN_PATH:
            await self._login(conn)(scope, receive, send)
        elif self._authorised(conn):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await HTMLResponse(_ASK_FOR_LOGIN, status_code=401)(scope, receive, send)

    def _authorised(self, conn: HTTPConnection) -> bool:
        cookie = conn.cookies.get(COOKIE_NAME, "")
        if cookie and hmac.compare_digest(cookie, self.session):
            return True
        scheme, _, bearer = conn.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and _same(bearer.strip(), self.token)

    def _login(self, conn: HTTPConnection) -> Response:
        if not _same(conn.query_params.get("token", ""), self.token):
            return HTMLResponse(_WRONG_TOKEN, status_code=403)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE_NAME, self.session, max_age=COOKIE_MAX_AGE,
                            httponly=True, samesite="lax",
                            secure=conn.url.scheme == "https")
        return response


def _is_open(path: str) -> bool:
    return path.startswith(OPEN_PREFIXES)


def _same(given: str, token: str) -> bool:
    # Constant-time so the token cannot be recovered a byte at a time.
    return hmac.compare_digest(given.encode(), token.encode())
