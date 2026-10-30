"""One rule for every Alpaca HTTP call: it ends.

``alpaca-py`` sends each request through a plain ``requests.Session`` with no
timeout. A socket that dies mid-request (this laptop sleeps with a pass in
flight; the far side resets while it is asleep and the reset never arrives)
then blocks its read forever. The loop thread holds the Autopilot lock while
it passes, so one such read froze the loop and every ``/api/autopilot`` call
behind it, with nothing in the log. Every client swaps in a session that
bounds each call; a timeout is a ``requests`` error, an ``OSError``, so the
one-retry rule for reads applies to it too.
"""

from __future__ import annotations

#: (connect, read) seconds. A read of 30 s is generous for Alpaca's REST
#: endpoints and short against a 5-minute poll.
HTTP_TIMEOUT: tuple[float, float] = (10.0, 30.0)


def bounded_session(timeout: tuple[float, float] = HTTP_TIMEOUT):
    """A ``requests.Session`` whose every call carries ``timeout`` unless the
    caller passed one. Imported lazily: the core never needs ``requests``."""
    import requests

    class BoundedSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return super().request(method, url, **kwargs)

    session = BoundedSession()
    session.timeout = timeout  # type: ignore[attr-defined]  # introspection only
    return session


def bound_client(client, timeout: tuple[float, float] = HTTP_TIMEOUT):
    """Give an ``alpaca-py`` REST client a bounded session and return it.

    The SDK keeps its session as ``_session`` (``alpaca.common.rest.RESTClient``);
    a release that renames it would make this raise at construction, in the
    offline test, never silently run unbounded.
    """
    if not hasattr(client, "_session"):
        raise AttributeError("alpaca-py client has no _session to bound")
    client._session = bounded_session(timeout)
    return client
