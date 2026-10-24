"""
Test package for Silu programming language.
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_fe_binary() -> str:
    """Path to the self-hosted front-end binary, rebuilt when the
    source is newer. The old build-if-missing pattern let a stale
    binary silently mask front-end source changes."""
    fe = os.path.join(REPO, "silu_fe")
    src = os.path.join(REPO, "selfhost", "silu_fe.si")
    if not os.path.exists(fe) or os.path.getmtime(src) > os.path.getmtime(fe):
        subprocess.run(
            [sys.executable, "-m", "silu", "build", src, "-o", fe],
            check=True, capture_output=True, cwd=REPO,
        )
    return fe
