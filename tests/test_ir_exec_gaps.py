"""IR-interpreter plane gaps that real programs hit: augmented
assignment on subscript/attribute targets (the pos[0] += 1 idiom),
n-ary and/or chains (parse-loop conditions), and jsonparse end to end
through `silu exec` - the reference semantics plane the benchmark
could not run on before.
"""

import os
import subprocess
import sys

from tests import REPO

PY = sys.executable


def _exec(source: str, stdin: str = "") -> str:
    ir = subprocess.run(
        [PY, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir.returncode == 0, ir.stderr
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".ir.json", delete=False
    ) as h:
        h.write(ir.stdout)
        path = h.name
    try:
        r = subprocess.run(
            [PY, "-m", "silu", "exec", path],
            input=stdin, capture_output=True, text=True, cwd=REPO,
        )
        assert r.returncode == 0, r.stderr
        return r.stdout
    finally:
        os.unlink(path)


def _interp(source: str, stdin: str = "") -> str:
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", source],
        input=stdin, capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def check(source: str, stdin: str = ""):
    expected = _interp(source, stdin)
    assert _exec(source, stdin) == expected


def test_aug_assign_subscript():
    check("pos = [10]\npos[0] += 5\nprint(pos[0])\n")
    check("xs = [2]\nxs[0] *= 7\nprint(xs[0])\n")
    check("d = {1: 10}\nd[1] += 5\nprint(d[1])\n")


def test_aug_assign_attribute():
    check(
        "class B:\n    w: int\n\nb = B(3)\nb.w += 4\nprint(b.w)\n"
    )


def test_nary_and_or():
    check(
        "a = 1\nb = 2\nc = 3\n"
        "if a > 0 and b > 0 and c > 0:\n    print('all')\n"
        "if a > 5 and b > 0 and c > 0:\n    print('no')\n"
        "if a > 5 or b > 5 or c > 5:\n    print('no2')\n"
        "if a > 0 or b > 0 or c > 0:\n    print('any')\n"
    )


def test_jsonparse_through_exec():
    """The benchmark now runs on the IR-interpreter plane; output must
    equal the compiled binary's quadruple."""
    gen = os.path.join(REPO, "scripts", "gen_json_input.py")
    doc = subprocess.run([PY, gen], capture_output=True, text=True)
    assert doc.returncode == 0, doc.stderr
    ir = subprocess.run(
        [PY, "-m", "silu", "ir",
         os.path.join(REPO, "benchmarks", "jsonparse.si"),
         "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir.returncode == 0, ir.stderr
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".ir.json", delete=False
    ) as h:
        h.write(ir.stdout)
        path = h.name
    try:
        r = subprocess.run(
            [PY, "-m", "silu", "exec", path],
            input=doc.stdout, capture_output=True, text=True, cwd=REPO,
        )
        assert r.returncode == 0, r.stderr
        total, count, checksum, names = r.stdout.split()
        assert (int(count), int(names), int(checksum)) == (3000, 3000, 22890)
    finally:
        os.unlink(path)
