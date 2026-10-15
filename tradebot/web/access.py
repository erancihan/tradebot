"""Optional access token, for reaching the dashboard over a network.

Off unless a token is configured (``TRADEBOT_WEB_TOKEN`` / ``--token``): on
localhost the machine's login is the access control. With one set, every
request needs either the session cookie that ``/login?token=...`` issues or an
``Authorization: Bearer <token>`` header. The cookie carries an HMAC of the
token, not the token, so a leaked cookie jar does not leak the secret that
mints new sessions; changing the token invalidates every cookie at once.

The phone push's signed batch links (``SIGNED_PATH``) skip the gate: ntfy
holds no cookie, and the link's HMAC is its own one-batch, one-verb credential.

The token is posted from a form, never put in a URL: a query string lands in
server access logs, browser history and Referer headers.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import parse_qs

from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE_NAME = "tradebot_session"
#: Assets a browser fetches before (or without) the cookie: the login page's
#: own styling, the PWA manifest and icons the home-screen shortcut needs.
OPEN_PREFIXES = ("/app/", "/static/")
LOGIN_PATH = "/login"
#: The phone push's signed batch links: their HMAC signature is the credential
#: (``tradebot.autopilot.links``), and ntfy cannot hold a session cookie.
SIGNED_PATH = re.compile(r"/api/autopilot/batches/[0-9]+/(approve|reject)", re.ASCII)
#: A year: the point is to log a phone in once, then use the home-screen icon.
COOKIE_MAX_AGE = 365 * 24 * 3600

#: Login responses must not be cached or leak where they came from.
_LOGIN_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

# Inline, because /static sits behind this gate too; dark like the app (slate-950).
_STYLE = """<meta name="theme-color" content="#020617">
<style>body{font:16px system-ui,sans-serif;max-width:24rem;margin:3rem auto;padding:0 1rem;
background:#020617;color:#e2e8f0}a{color:#34d399}label{color:#94a3b8}
input,button{font:inherit;padding:.5rem;width:100%;min-height:44px;box-sizing:border-box;
margin-top:.5rem;border-radius:.5rem;border:1px solid #334155;background:#0f172a;color:inherit}
button{background:#059669;border-color:#059669;color:#fff;font-weight:600}
.err{color:#fda4af}</style>
"""
_HEAD = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tradebot: sign in</title>
""" + _STYLE
_ASK_FOR_LOGIN = _HEAD + """<p>This dashboard needs its access token.</p>
<p><a href="/login">Sign in</a> once in this browser and paste it.</p>
"""
_LOGIN_FORM = _HEAD + """<h1>tradebot</h1>
{error}
<form method="post" action="/login">
<label for="token">Access token (TRADEBOT_WEB_TOKEN)</label>
<input id="token" name="token" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Sign in</button>
</form>
"""
_WRONG_TOKEN = '<p class="err">That is not the token this dashboard was started with.</p>'


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
            response = await self._login(Request(scope, receive))
            await response(scope, receive, send)
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

    async def _login(self, request: Request) -> Response:
        if request.method != "POST":
            return _login_page()
        try:
            posted = await _posted_token(request)
        except _Refused as refusal:
            # Raw ASGI middleware has no exception handler above it, so the
            # refusal becomes a response here instead of a 500.
            return Response(refusal.detail, status_code=refusal.status_code,
                            headers=_LOGIN_HEADERS)
        if not _same(posted, self.token):
            return _login_page(_WRONG_TOKEN, status_code=403)
        response = RedirectResponse("/", status_code=303, headers=_LOGIN_HEADERS)
        response.set_cookie(COOKIE_NAME, self.session, max_age=COOKIE_MAX_AGE,
                            httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
        return response


def _login_page(error: str = "", status_code: int = 200) -> Response:
    return HTMLResponse(_LOGIN_FORM.replace("{error}", error),
                        status_code=status_code, headers=_LOGIN_HEADERS)


class _Refused(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


#: A login form is a few dozen bytes. The read happens before any auth, so
#: it is bounded: an attacker must not be able to make the server buffer an
#: arbitrarily large body.
MAX_LOGIN_BODY = 4096


async def _posted_token(request: Request) -> str:
    # Parsed by hand: Starlette's request.form() needs python-multipart, and
    # one urlencoded field does not justify a dependency.
    fields = parse_qs((await _bounded_body(request)).decode("utf-8", "replace"))
    return fields.get("token", [""])[0]


async def _bounded_body(request: Request) -> bytes:
    """Read the form body, refusing anything that is not a small urlencoded form."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type != "application/x-www-form-urlencoded":
        raise _Refused(415, "login expects a urlencoded form")
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit() or int(declared) > MAX_LOGIN_BODY:
        raise _Refused(413, "login body too large")
    chunks, total, limit = [], 0, int(declared)
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:                   # the declared length lied
            raise _Refused(413, "login body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _is_open(path: str) -> bool:
    return path.startswith(OPEN_PREFIXES) or SIGNED_PATH.fullmatch(path) is not None


def _same(given: str, token: str) -> bool:
    # Constant-time so the token cannot be recovered a byte at a time.
    return hmac.compare_digest(given.encode(), token.encode())
