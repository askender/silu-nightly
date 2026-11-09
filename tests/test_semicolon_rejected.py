"""`;` statement separators are not part of Silu.

The Python-plane front end parses via CPython's ast module, which
would happily accept `a = 1; b = 2` - a divergence from the
self-hosted and Rust front ends (both reject with "expected end of
line"). The strict subset is now pinned at the shared parse choke
point (silu.importer.expand_imports_tree); this test keeps the three
planes aligned on the error path and guards the string/comment
immunity of the tokenize-based scan.
"""

import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ir(src):
    with tempfile.NamedTemporaryFile(suffix=".si", mode="w",
                                     delete=False) as h:
        h.write(src)
        path = h.name
    try:
        return subprocess.run(
            [sys.executable, "-m", "silu", "ir", path, "--format", "json"],
            capture_output=True, text=True, cwd=REPO)
    finally:
        os.unlink(path)


def test_semicolon_separator_rejected():
    r = _ir("x = 1; y = 2\nprint(x + y)\n")
    assert r.returncode != 0
    assert "not part of Silu" in (r.stderr + r.stdout)


def test_semicolon_in_string_fine():
    r = _ir('s = "a;b;c"\nprint(len(s))\n')
    assert r.returncode == 0, (r.stderr + r.stdout)[:200]
    assert '"const", 5' in r.stdout.replace(" ", "").replace(
        '"const":5', '"const",5') or "a;b;c" in r.stdout


def test_semicolon_in_comment_fine():
    r = _ir("# a;b comment\nx = 1\n")
    assert r.returncode == 0, (r.stderr + r.stdout)[:200]


def test_selfhost_and_python_plane_agree_on_reject():
    # the self-hosted front end has always rejected; keep the pair in
    # lockstep (the error TEXT is not pinned, only accept/reject)
    shb = os.path.join(REPO, "silu_fe")
    if not os.path.exists(shb):
        import pytest
        pytest.skip("self-hosted front end binary not built")
    sh = subprocess.run([shb], input=b"x = 1; y = 2\nprint(x+y)\n",
                        capture_output=True)
    assert sh.returncode != 0
