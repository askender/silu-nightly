"""The built-in Json sum type (RFC S2): heterogeneous containers get
a typed home.

Three planes assert identical output for the same program: the
typed-compiled binary, the AST interpreter, and the CPython plane
(pycompat). The IR interpreter (exec) plane does not know the
json_* builtins yet - recorded as an S2c gap in the RFC.

Tag table: 0=null 1=int 2=float 3=bool 4=str 5=list 6=dict.
"""

import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

SCALARS = """
x: Json = 5
y: Json = "hi"
z: Json = 3.5
w: Json = True
print(json_tag(x), json_tag(y), json_tag(z), json_tag(w))
print(json_int(x), json_str(y), json_float(z), json_bool(w))
json_free(x)
json_free(y)
json_free(z)
json_free(w)
"""

CONTAINERS = """
x: Json = 5
y: Json = "hi"
items: list[Json] = [x, y, 7]
items.append(False)
print(json_int(items[0]) + len(items), json_str(items[1]))
items[1] = "no"
print(json_tag(items[1]), len(json_str(items[1])))
d: dict[str, Json] = {"a": 1, "b": "two"}
d["c"] = False
print(json_int(d["a"]), json_str(d["b"]), json_bool(d["c"]), len(d))
freed = 0
for it in items:
    json_free(it)
    freed += 1
for k in d:
    json_free(d[k])
    freed += 1
print(freed)
"""

WRONG_MEMBER = 'x: Json = 5\nprint(json_str(x))\n'


def _typed_output(source: str) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".si", delete=False) as h:
        h.write(source)
        path = h.name
    try:
        build = subprocess.run(
            [PY, "-m", "silu", "build", path, "-o", path + ".bin"],
            capture_output=True, text=True, cwd=REPO, timeout=300,
        )
        assert build.returncode == 0, build.stderr[-500:]
        run = subprocess.run(
            [path + ".bin"], capture_output=True, text=True, timeout=60
        )
        assert run.returncode == 0, run.stderr[-500:]
        return run.stdout
    finally:
        os.unlink(path)
        if os.path.exists(path + ".bin"):
            os.unlink(path + ".bin")


def _interpreter_output(source: str) -> str:
    import ast

    from silu.interpreter import SiluInterpreter

    itp = SiluInterpreter()
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        itp.visit(ast.parse(source))
    return buf.getvalue()


def _cpython_output(source: str) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".si", delete=False, dir=REPO
    ) as h:
        h.write(source)
        path = h.name
    try:
        r = subprocess.run(
            [PY, "tools/pycompat.py", os.path.basename(path)],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        assert r.returncode == 0, r.stderr[-500:]
        return r.stdout
    finally:
        os.unlink(path)


def test_scalars_three_planes():
    out = _typed_output(SCALARS)
    assert out == "1 4 2 3\n5 hi 3.5 True\n"
    assert _interpreter_output(SCALARS) == out
    assert _cpython_output(SCALARS) == out


def test_containers_three_planes():
    out = _typed_output(CONTAINERS)
    lines = out.strip().split("\n")
    assert lines[0] == "9 hi"
    assert lines[1] == "4 2"
    assert lines[2] == "1 two False 3"
    assert lines[3] == "7"  # 4 list elements + 3 dict values freed
    assert _interpreter_output(CONTAINERS) == out
    assert _cpython_output(CONTAINERS) == out


def test_wrong_member_aborts_loudly():
    """json_str on an int member aborts - the checked-error policy,
    not a silent default."""
    # aborted before the print; non-zero exit asserted in the next test
    with pytest.raises(AssertionError):
        _typed_output(WRONG_MEMBER)


def test_wrong_member_exit_code():
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".si", delete=False) as h:
        h.write(WRONG_MEMBER)
        path = h.name
    try:
        build = subprocess.run(
            [PY, "-m", "silu", "build", path, "-o", path + ".bin"],
            capture_output=True, text=True, cwd=REPO, timeout=300,
        )
        assert build.returncode == 0
        run = subprocess.run(
            [path + ".bin"], capture_output=True, text=True, timeout=60
        )
        assert run.returncode != 0
        # silu_panic prints to stdout and exits non-zero
        assert "TypeError" in run.stdout
    finally:
        os.unlink(path)
        if os.path.exists(path + ".bin"):
            os.unlink(path + ".bin")
