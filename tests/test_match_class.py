"""Class patterns with narrowing: `case JInt(n)` checks the instance's
class id and binds payload fields with their DECLARED kinds - the arm's
downstream arithmetic/field reads compile static. Verified on every
surface (AST interpreter, IR interpreter, typed build) with identical
output, plus the self-hosted front end emits the same IR.
"""

import json
import subprocess
import sys


from tests import REPO, ensure_fe_binary

PY = sys.executable


def check_all_planes(source: str, expected: str):
    """interpret == exec(IR) == compiled binary == fe-front-end IR."""
    import os
    import tempfile

    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", source],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected

    ir = subprocess.run(
        [PY, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir.returncode == 0, ir.stderr

    with tempfile.TemporaryDirectory() as td:
        ir_path = os.path.join(td, "p.ir.json")
        with open(ir_path, "w") as h:
            h.write(ir.stdout)
        x = subprocess.run(
            [PY, "-m", "silu", "exec", ir_path],
            capture_output=True, text=True, cwd=REPO,
        )
        assert x.returncode == 0, x.stderr
        assert x.stdout == expected
        src = os.path.join(td, "p.si")
        bin_ = os.path.join(td, "p")
        with open(src, "w") as h:
            h.write(source)
        b = subprocess.run(
            [PY, "-m", "silu", "build", src, "-o", bin_],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run([bin_], capture_output=True, text=True)
        assert run.stdout == expected

        # the self-hosted front end emits identical IR for it
        fe = ensure_fe_binary()
        fe_ir = subprocess.run(
            [fe], stdin=open(src), capture_output=True, text=True,
            cwd=os.path.dirname(src),
        )
        assert fe_ir.returncode == 0, fe_ir.stderr
        assert json.loads(fe_ir.stdout) == json.loads(ir.stdout)


VARIANTS = '''class JInt:
    v: int

class JStr:
    v: str

class JArr:
    items: list

'''


def test_single_variant_narrowing():
    check_all_planes(
        VARIANTS
        + '''def f(it) -> int:
    match it:
        case JInt(n):
            return n * 2
    return -1

print(f(JInt(21)))
print(f(JStr("x")))
''',
        "42\n-1\n",
    )


def test_mixed_variants_accumulate():
    """The consumer's arithmetic rides the narrowed field kinds."""
    check_all_planes(
        VARIANTS
        + '''def total_of(items) -> int:
    total: int = 0
    for it in items:
        match it:
            case JInt(n):
                total += n
            case JStr(w):
                total += len(w)
    return total

print(total_of([JInt(5), JStr("abc"), JInt(7), JArr([])]))
''',
        "15\n",
    )


def test_nested_match_inside_arm():
    check_all_planes(
        VARIANTS
        + '''def count_items(x) -> int:
    match x:
        case JArr(items):
            t: int = 0
            i: int = 0
            while i < len(items):
                match items[i]:
                    case JInt(n):
                        t += n
                i += 1
            return t
    return 0

print(count_items(JArr([JInt(3), JInt(4), JStr("z")])))
''',
        "7\n",
    )


def test_module_level_capture_does_not_poison_functions():
    """A module-level match capture sharing a name with a function
    local must not split the function's storage slot (the historical
    miscompile: the initializer's store vanished into the first of two
    allocas and the function returned 0)."""
    check_all_planes(
        '''def digit_value(ch: str) -> int:
    if ch == "0":
        return 0
    if ch == "5":
        return 5
    return 2

def num2(s: str) -> int:
    n: int = 0
    i: int = 0
    while i < len(s):
        n = n * 10 + digit_value(s[i])
        i += 1
    return n

print(num2("250"))
sel = 1
match sel:
    case 0:
        print("zero")
    case n:
        print(n)
''',
        "250\n1\n",
    )


def test_keyword_pattern():
    check_all_planes(
        VARIANTS
        + '''def f(it) -> int:
    match it:
        case JInt(v=n):
            return n + 1
    return 0

print(f(JInt(41)))
''',
        "42\n",
    )


def test_compiled_jsonparse_matches_original_output():
    """The rewritten benchmark (variant classes + narrowing) must print
    exactly what the original dynamic version printed."""
    import os
    import tempfile

    gen = os.path.join(REPO, "scripts", "gen_json_input.py")
    doc = subprocess.run([PY, gen], capture_output=True, text=True)
    assert doc.returncode == 0, doc.stderr
    with tempfile.TemporaryDirectory() as td:
        bin_ = os.path.join(td, "jp")
        b = subprocess.run(
            [PY, "-m", "silu", "build",
             os.path.join(REPO, "benchmarks", "jsonparse.si"), "-o", bin_],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run(
            [bin_], input=doc.stdout, capture_output=True, text=True
        )
        assert run.returncode == 0, run.stderr
        # total id-sum, count, name checksum, name count - the same
        # quadruple the dynamic version printed on this generator
        total, count, checksum, names = run.stdout.split()
        assert (int(count), int(names)) == (3000, 3000)
        assert int(checksum) == 22890
