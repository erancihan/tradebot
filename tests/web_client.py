"""One way to build a dashboard TestClient, shared by the web tests.

Starlette's TestClient sends ``Host: testserver`` by default, which the
dashboard's production allowlist deliberately refuses. Talking to
``http://localhost`` exercises the real allowlist instead of widening it.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

LOCAL = "http://localhost"


def local_client(app: Any, **kwargs: Any) -> TestClient:
    kwargs.setdefault("base_url", LOCAL)
    return TestClient(app, **kwargs)
