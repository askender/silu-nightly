"""Memory-boundedness gates for the typed plane's copy semantics.

The v1.15.0 copy-into wiring leaked a whole-source copy per field-slice
assignment; every correctness gate stayed green because a dead copy does
not change program output. These gates close that hole EMPIRICALLY: each
copy-semantics pattern runs in a loop against a large string, and a
whole-value leak would multiply peak RSS by the iteration count (OOM)
instead of staying constant. Correct patterns stay within tens of MB.
"""

import resource
import subprocess
import sys

import pytest

from tests import REPO

PY = sys.executable

# (name, loop body). Each runs N iterations against a large string.
PATTERNS = [
    ("field_slice", 't: str = big[a:a+8]'),      # the v1.16.2 fix
    ("field_char", 't: str = big[a]'),
    ("field_whole", 't: str = big'),
    ("field_cmp", 'ok = big[a:a+2] == "ab"'),    # lexer hot path
    ("list_elem", 't: str = vocab[a % 3]'),      # copy-into target
    ("list_append", 'vocab2.append("xy")'),
    ("dict_key", 'd["k" + str(a % 10)] = a'),
    ("concat", 'acc = acc + "xy"'),              # in-place append
    ("aug", 'acc += "xy"'),
    ("len_field", 'n = len(big)'),
    ("char_view_ord", 'n = ord(big[a])'),
    ("contains", 'ok = "zz" in big'),
    ("borrow_arg", 'n = sink(big)'),
    ("ret_copy", 't: str = make(a)'),
    ("field_write", 'c.f = "xy"'),
    ("method_strip", 't: str = big.strip()'),
]

TEMPLATE = '''class C:
    f: str

def sink(s: str) -> int:
    return len(s)

def make(i: int) -> str:
    return "v" + str(i)

c = C("z")
big: str = "abcdefgh" * 32000
vocab: list[str] = ["aa", "bb", "cc"]
vocab2: list[str] = []
d: dict[str, int] = {}
acc: str = ""
t: str = ""
ok = False
n = 0
for i in range(30000):
    a = i % 250000
    {body}
print(len(t) + n + (1 if ok else 0))
'''

# A single whole-string leak at 256KB x 30000 iterations would allocate
# ~7.5GB; every healthy pattern measured below ~40MB on this template.
LIMIT_MB = 350


@pytest.mark.parametrize("name,body", PATTERNS, ids=[p[0] for p in PATTERNS])
def test_copy_semantics_loop_is_memory_bounded(name, body, tmp_path):
    if subprocess.run(["clang", "--version"], capture_output=True).returncode != 0:
        pytest.skip("clang not available")
    si = tmp_path / f"{name}.si"
    si.write_text(TEMPLATE.replace("{body}", body))
    exe = tmp_path / name
    build = subprocess.run(
        [PY, "-m", "silu", "build", str(si), "-o", str(exe)],
        capture_output=True, text=True, cwd=REPO, timeout=600,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(exe)], capture_output=True, timeout=300,
    )
    assert run.returncode == 0, (name, run.stderr[:200])
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    subprocess.run([str(exe)], capture_output=True, timeout=300, check=True)
    peak_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # ru_maxrss is a running max over ALL children of this pytest
    # process; only a NEW maximum can be attributed to this pattern
    grew = peak_kb - before
    assert grew < LIMIT_MB * 1024, (
        f"{name}: peak RSS grew by {grew/1024:.0f}MB over the previous "
        f"running max - a copy-semantics loop is leaking whole values "
        f"(limit {LIMIT_MB}MB)"
    )
