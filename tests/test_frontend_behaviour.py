"""Runs the frontend's Node behaviour tests (`frontend/test.mjs`) in the suite.

Skipped where Node or the frontend's dev dependencies are not installed (the
Python CI job); the frontend CI job runs them through `npm test`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def test_frontend_behaviour_tests_pass():
    node = shutil.which("node")
    if node is None or not (FRONTEND / "node_modules" / "esbuild").exists():
        pytest.skip("node or frontend/node_modules not installed (make install-web)")
    done = subprocess.run([node, "test.mjs"], cwd=FRONTEND, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
