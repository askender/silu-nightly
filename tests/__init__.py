"""
Test package for Silu programming language.
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_fe_binary() -> str:
    """Path to the self-hosted front-end binary, rebuilt when any of
    its sources is newer. The old build-if-missing pattern let a stale
    binary silently mask front-end source changes.

    silu_fe.si is main-free (siluc.si imports it inline); the runnable
    binary comes from the silu_fe_main.si wrapper."""
    fe = os.path.join(REPO, "silu_fe")
    sources = [
        os.path.join(REPO, "selfhost", "silu_fe_main.si"),
        os.path.join(REPO, "selfhost", "silu_fe.si"),
    ]
    stale = not os.path.exists(fe) or any(
        os.path.getmtime(s) > os.path.getmtime(fe) for s in sources
    )
    if stale:
        subprocess.run(
            [sys.executable, "-m", "silu", "build", sources[0], "-o", fe],
            check=True, capture_output=True, cwd=REPO,
        )
    return fe
