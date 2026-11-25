"""Lint is part of the gate: `pytest` all-green must imply `ruff` clean.

The CI lint step was red for six consecutive pushes (2026-11-22..24) while
every handoff claimed "all gates green", because the local gate habit was
pytest + the two harness planes and none of them lints. An undefined name in
a converter arm (F821) shipped that way and broke `strbuf(<non-const>)` on
the python plane. This test runs the exact CI command so the next such
change fails locally first.
"""

import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_ruff_clean_on_ci_paths():
    ruff = shutil.which("ruff")
    cmd = [sys.executable, "-m", "ruff"] if ruff is None else [ruff]
    probe = subprocess.run(cmd + ["--version"], capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("ruff not installed")
    # the same paths and the same pyproject configuration as ci.yml
    r = subprocess.run(cmd + ["check", "silu/", "tools/"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
