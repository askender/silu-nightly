"""The compiler binary itself under a real AddressSanitizer.

tests/test_asan_runtime.py runs programs. This one runs the COMPILER:
the same runtime lives inside `siluc1`, and in 2026-11 five crash
reports in one session came from it - a code point walker reading one
byte past a string buffer, on inputs no test ever fed it.

The instrumented compiler must bring every corpus file through with no
report, exit 0, and the same bytes as the normal binary. That last
clause is also the only gate that runs the self-hosted converter on
`selfhost/ir2c.si` and on its own source. ir2c.si had not been
compilable by `siluc1` since 2026-10-25 (a segfault on an attribute
store to an instance read out of a typed list) and nothing noticed,
because nothing but the Python plane ever built it.

Slow layer: excluded from the CI `fast` job, run by the `gates` job and
by the full local pytest (about three minutes).
"""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests"))
sys.path.insert(0, os.path.join(REPO, "reference"))

import asan_run  # noqa: E402
import diff_harness as dh  # noqa: E402
import test_semantics_vs_cpython as sem  # noqa: E402

SILUC1 = os.path.join(REPO, "siluc1")
# (source, cwd): the converter's wrapper only resolves its imports from
# its own directory, and siluc1 reads the program from stdin
INPUTS = [(rel, os.path.dirname(os.path.join(REPO, rel)))
          for rel in dh.CORPUS_LL] + [
    ("selfhost/ir2c.si", os.path.join(REPO, "selfhost")),
    ("selfhost/silu_conv_main.si", os.path.join(REPO, "selfhost")),
]


@pytest.fixture(scope="module")
def instrumented():
    """`siluc1`, built from the Python plane's IR with every function
    attributed (tools/asan_run.py)."""
    sem._ensure_siluc1()  # also generates typed_codegen_flat.si
    work = tempfile.mkdtemp(prefix="siluc_asan_")
    ir_json = os.path.join(work, "siluc.json")
    r = subprocess.run(
        [sys.executable, "-m", "silu", "ir",
         os.path.join(REPO, "selfhost", "siluc.si"), "-o", ir_json],
        capture_output=True, cwd=REPO, timeout=1800)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-500:]
    r = subprocess.run([sys.executable, "-m", "silu", "llvm", ir_json],
                       capture_output=True, cwd=REPO, timeout=1800)
    assert r.returncode == 0 and r.stdout, (
        r.stderr + r.stdout).decode("utf-8", "replace")[-500:]
    binary = asan_run.build(r.stdout.decode("utf-8", "replace"), work)
    yield binary
    shutil.rmtree(work, ignore_errors=True)


@pytest.mark.parametrize("rel,cwd", INPUTS, ids=[rel for rel, _c in INPUTS])
def test_compiler_is_memory_safe(instrumented, rel, cwd):
    with open(os.path.join(REPO, rel), "rb") as h:
        src = h.read()
    ref = subprocess.run([SILUC1], input=src, capture_output=True,
                         cwd=cwd, timeout=1800)
    result = asan_run.run(instrumented, src, timeout=1800, cwd=cwd)
    assert result.kind is None, "%s: %s\n%s" % (
        rel, result.summary, result.stderr[-3000:])
    assert result.returncode == 0 and ref.returncode == 0, (
        "%s: asan compiler exited %s, normal %s\n%s\n%s" % (
            rel, result.returncode, ref.returncode,
            result.stdout[-500:], result.stderr[-500:]))
    assert result.stdout == ref.stdout, (
        "%s: the instrumented compiler's .ll differs from siluc1's "
        "(%d vs %d bytes)" % (rel, len(result.stdout), len(ref.stdout)))
