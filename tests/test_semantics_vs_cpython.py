"""Semantics gate: compiled Silu must agree with CPython.

The parity gates pin BYTES between the compiler's own planes - they
prove the planes agree, not that any of them is right. In 2026-11 a
304-probe sweep found ~20 ways for `silu build` to accept a program and
produce a wrong answer or a segfault while every byte gate was green:
`a, b = b, a` on strings, `"hello".count("l")`, `print([None])`, `2 ** 3`
with runtime operands, `range(0, 10, 3)`, keyword arguments, ...

Every case here is plain Python, so the expected output is produced by
CPython when the test runs - never hand-written (STATUS lesson 1: hand
written expectations were wrong four times). `MUST_REJECT` cases are
constructs the language does not support: the contract is a loud
compile-time error, not a silently different program.

Each case runs on two planes. The converter ships twice - as the Python
module behind `silu build` and as the Silu twin that builds `siluc1` - and
a gate on one plane cannot tell whether the other kept up.
"""

import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILUC1 = os.path.join(REPO, "siluc1")


def _build_and_run(src: str, stdin: str = None):
    """(rc, stdout) of `silu build` + run; (None, message) on a build
    error."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "p.si")
        bin_ = os.path.join(td, "p")
        with open(path, "w") as h:
            h.write(src)
        r = subprocess.run([sys.executable, "-m", "silu", "build", path,
                            "-o", bin_], capture_output=True, text=True,
                           cwd=REPO, timeout=300)
        if r.returncode != 0:
            return None, (r.stderr + r.stdout).strip().split("\n")[-1]
        r = subprocess.run([bin_], input=stdin, capture_output=True,
                           text=True, timeout=60)
        return r.returncode, r.stdout


def _ensure_siluc1():
    """The self-hosted plane binary (a gitignored build artifact), rebuilt
    from source when missing or older than its sources."""
    newest = max(
        os.path.getmtime(os.path.join(REPO, "selfhost", f))
        for f in os.listdir(os.path.join(REPO, "selfhost"))
        if f.endswith(".si")
    )
    if not os.path.exists(SILUC1) or os.path.getmtime(SILUC1) < newest:
        sys.path.insert(0, os.path.join(REPO, "tools"))
        import selfhost_build
        selfhost_build.ensure_siluc()


def _selfhosted_and_run(src: str, stdin: str = None):
    """(rc, stdout) of the self-hosted compiler's .ll through clang, then
    run; (None, message) when the self-hosted plane refuses the program."""
    _ensure_siluc1()
    with tempfile.TemporaryDirectory() as td:
        ll = os.path.join(td, "p.ll")
        bin_ = os.path.join(td, "p")
        r = subprocess.run([SILUC1], input=src, capture_output=True,
                           text=True, cwd=REPO, timeout=600)
        if r.returncode != 0:
            return None, (r.stdout + r.stderr).strip().split("\n")[-1]
        with open(ll, "w") as h:
            h.write(r.stdout)
        c = subprocess.run(["clang", "-O1", ll, "-lm", "-o", bin_],
                           capture_output=True, text=True, timeout=300)
        if c.returncode != 0:
            return None, "clang: " + c.stderr.strip().split("\n")[-1]
        r = subprocess.run([bin_], input=stdin, capture_output=True,
                           text=True, timeout=60)
        return r.returncode, r.stdout


def _plane(plane: str):
    return {"python": _build_and_run, "selfhosted": _selfhosted_and_run}[plane]


def _cpython(src: str, stdin: str = None):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "p.py")
        with open(path, "w") as h:
            h.write(src)
        r = subprocess.run([sys.executable, path], input=stdin,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout


def _interp(src: str):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "p.si")
        with open(path, "w") as h:
            h.write(src)
        r = subprocess.run([sys.executable, "-m", "silu", "interpret", path],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, cwd=REPO, timeout=120)
        return r.returncode, r.stdout


PLANES = ["python", "selfhosted"]

# (id, source) - stdout must equal CPython's byte for byte
MATCH_CPYTHON = [
    # --- integer pow: the exactness guard was inverted, and the libc
    # detour rounded every result above 2**53
    ("pow_runtime_exponent",
     "a = 2\nb = 3\nprint(a ** b, 5 ** 2, 3 ** 0, 0 ** 0, (-2) ** 3, 1 ** 1000)\n"),
    ("pow_exact_beyond_double",
     "x = 7\nn = 22\nprint(x ** n, 3 ** 39, (-3) ** 39, 10 ** 18, 2 ** 62, (-2) ** 63)\n"),
    ("pow_in_loops_and_calls",
     "def pw(x: int, n: int) -> int:\n    return x ** n\n"
     "t = 0\nfor i in range(12):\n    t += 2 ** i\n"
     "print(pw(2, 10), pw(-3, 3), pw(0, 5), t, (2 ** 3) ** 2, 2 ** 3 ** 2)\n"),
    # --- range: the third argument was dropped silently
    ("range_step_literals",
     "out = []\nfor i in range(0, 10, 3):\n    out.append(i)\n"
     "for i in range(10, 0, -3):\n    out.append(i)\n"
     "for i in range(0, 0, 2):\n    out.append(-1)\n"
     "for i in range(10, 5, -1):\n    out.append(i)\nprint(out)\n"),
    ("range_step_variables",
     "n = 2\nm = -3\nout = []\nfor i in range(1, 8, n):\n    out.append(i)\n"
     "for i in range(10, 0, m):\n    out.append(i)\nprint(out)\n"),
    ("range_one_and_two_args_unchanged",
     "out = []\nfor i in range(4):\n    out.append(i)\n"
     "for i in range(2, 6):\n    out.append(i)\nprint(out)\n"),
    ("range_as_value_folded",
     "a = list(range(3))\nprint(a, len(a), len(range(10)), len(range(3, 12, 2)), "
     "len(range(10, 0, -3)), list(range(0)), list(range(10, 0, -2)))\n"),
    # --- tuple assignment: strings were stored from freed memory
    ("tuple_swap_strings",
     'a = "ab"\nb = "cd"\na, b = b, a\nprint(a, b)\n'
     'a, b = b + "1", a + "2"\nprint(a, b)\n'),
    ("tuple_rotate_strings",
     'a = "ab"\nb = "cd"\nc = "ef"\na, b, c = c, a, b\nprint(a, b, c)\n'
     'a, b, c = c, a, b\nprint(a, b, c)\n'),
    ("tuple_swap_in_function_and_annotated",
     'def f() -> None:\n    s = "s1"\n    t = "s2"\n    s, t = t, s\n'
     '    print(s, t, len(s), len(t))\nf()\n'
     'p: str = "p"\nq: str = "q"\np, q = q, p\nprint(p, q)\n'),
    ("tuple_assign_mixed_kinds",
     'x, y = "x", "y"\nm, n = 1, "m"\nm, n = n, m\n'
     'u, v = ["w", "z"]\nu += "!"\nprint(x, y, m, n, u, v)\n'),
    ("tuple_unpack_from_call",
     "def f() -> list:\n    return [1, 'x']\na, b = f()\nprint(a, b)\n"),
    # --- count / index: the boxed method map is keyed by NAME only
    ("str_count",
     's = "ababab"\nprint(s.count("a"), s.count("z"), s.count("ab"), s.count(""), '
     's.count("abc"))\nprint("hello".count("l"), "".count(""), "aaa".count("aa"))\n'
     't = "日本語日本"\nprint(t.count("日"), t.count("本語"), t.count(""), len(t))\n'
     'u = "héllo"\nprint(u.count("é"), u.count("l"))\n'),
    ("str_count_dynamic_receiver",
     'def get() -> object:\n    return "hello"\n\nd = get()\nprint(d.count("l"), d.count("z"))\n'),
    ("typed_list_count_index",
     "li: list[int] = [1, 2, 2, 3]\nprint(li.count(2), li.count(9), li.index(3), li.index(1))\n"
     "lf: list[float] = [1.5, 2.5, 1.5]\nprint(lf.count(1.5), lf.index(2.5))\n"
     'ls: list[str] = ["ab", "cd", "ab"]\nprint(ls.count("ab"), ls.index("cd"), ls.count("zz"))\n'
     's = "cd"\nprint(ls.count(s), ls.index(s))\n'),
    ("list_count_untyped_unchanged",
     "l = [1, 2, 2, 3]\nprint(l.count(2), l.count(9), ['a', 'b', 'a'].count('a'))\n"),
    # --- containers holding None: the element printer read a null tag
    ("print_none_in_containers",
     "print([None])\nprint({'k': None})\nprint([None, 1], {'a': [None]}, [[None], [1]])\n"
     "print([1, 'a', 2.5, True, None, [2], {'k': 1}])\n"),
    ("print_typed_object_list_with_none",
     "os: list[object] = [1, 'a', None]\nprint(os)\n"),
    # --- dict[str, str]: boxing one (print) was a bare KeyError
    ("print_str_valued_dict",
     'd: dict[str, str] = {"k": "a"}\nprint(d, len(d))\ne: dict[str, str] = {}\nprint(e)\n'
     'd["j"] = "b"\nprint(d, d["j"], len(d))\n'),
    ("print_every_typed_dict_family",
     "a: dict[int, int] = {1: 2}\nb: dict[int, float] = {1: 1.5}\n"
     'c: dict[str, int] = {"a": 1}\nd: dict[str, float] = {"a": 1.5}\n'
     'e: dict[str, str] = {"a": "x"}\nprint(a, b, c, d, e)\n'),
    # --- keyword arguments were dropped on the floor: f(b=3, a=4) was
    # a zero-argument call that printed 0
    ("keyword_arguments_bound_by_name",
     "def f(a: int, b: int) -> int:\n    return a * 10 + b\n"
     "print(f(1, 2), f(b=3, a=4), f(5, b=6), f(a=1, b=2), f(b=9, a=1))\n"),
    ("keyword_arguments_str_params",
     "def g(name: str, n: int) -> str:\n    return name + ':' + str(n)\n"
     "print(g(n=3, name='x'), g('y', n=4), g(name='z', n=5))\n"),
    ("dict_keyword_constructor",
     "d = dict(a=1, b=2)\nprint(d, d['a'], d['b'], len(d))\n"),
    ("print_separator",
     'print("a", "b", sep="")\nprint("a", "b", sep="-")\n'
     'print("x", end="")\nprint("y")\nprint(1, 2.5, [1], sep=" | ")\n'),
    # --- a dict mutated under its own loop. The typed loop hoisted
    # table/keys/vals once: a store in the body that reindexed the table
    # left it walking freed arrays (values skipped, then a segfault) - and
    # it walked the hash table, not the insertion order CPython shows
    ("typed_dict_iteration_insertion_order",
     "d: dict[int, int] = {}\nd[5] = 50\nd[1] = 10\nd[3] = 30\nd[9] = 90\n"
     "for k in d:\n    print(k, d[k])\nprint(d)\ndel d[1]\nd[7] = 70\ndel d[3]\n"
     "for k, v in d.items():\n    print(k, v)\n"
     "for v in d.values():\n    print(v)\nprint(d)\n"),
    ("typed_dict_update_values_in_loop",
     "d: dict[int, int] = {}\ni = 0\nwhile i < 60:\n    d[i] = i\n    i += 1\n"
     "for k in d:\n    d[k] = k * 2\nprint(d[0], d[17], d[59], len(d))\n"
     'e: dict[str, int] = {"b": 2, "a": 1}\nfor w in e:\n    e[w] = e[w] * 10\n'
     'print(e, e["a"], e["b"])\n'),
    ("typed_dict_growth_keeps_insertion_order",
     "d: dict[int, int] = {}\ni = 0\nwhile i < 200:\n    d[i * 7 % 200] = i\n"
     "    i += 1\nn = 0\nfor k in d:\n    n = (n + k) % 1000003\n    d[k] = k * 2\n"
     "print(len(d), n, d[0], d[1], d[3], d[199])\n"),
    ("dynamic_dict_iteration",
     "d: dict = {1: 1, 2: 2, 3: 3}\nfor k in d:\n    d[k] = d[k] * 10\n"
     "for k, v in d.items():\n    print(k, v)\nd['x'] = 1\n"
     "for k in d:\n    print(k)\nprint(d)\n"),
    ("dict_delete_then_break_is_fine",
     "d: dict[int, int] = {1: 1, 2: 2}\nfor k in d:\n    del d[k]\n    break\n"
     "print('done', len(d), d[2])\n"),
    ("str_valued_dict_iteration_binds_copies",
     'd: dict[str, str] = {"b": "B", "a": "A"}\nfor k, v in d.items():\n'
     '    print(k, v)\n    v += "!"\n    print(v)\nprint(d)\n'
     'for v in d.values():\n    print(v)\nprint(d)\n'),
    # --- list loops kept a snapshot of the length: a worklist
    # (`for x in xs: xs.append(...)`) never saw its own additions
    ("list_grows_into_its_own_loop",
     "xs: list[int] = [1, 2, 3]\nt = 0\nfor x in xs:\n    t += x\n"
     "    if len(xs) < 30:\n        xs.append(x * 10)\nprint(t, len(xs))\n"
     "ys: list[int] = []\ni = 0\nwhile i < 20:\n    ys.append(i)\n    i += 1\n"
     "n = 0\nfor y in ys:\n    ys.pop()\n    n += 1\nprint(n, len(ys))\n"
     "dyn = [1, 2]\nc = 0\nfor e in dyn:\n    c += e\n    dyn.append(0)\n"
     "    if len(dyn) > 10:\n        break\nprint(c, len(dyn))\n"),
    # --- a str loop kept walking the buffer its body had replaced
    ("str_loop_body_rebinds_iterated_name",
     "def scan(s: str) -> int:\n    n = 0\n    for c in s:\n        n += 1\n"
     '        s = s + "x"\n    return n\n\n'
     "def grow(s: str) -> str:\n    out = \"\"\n    for c in s:\n"
     '        out += c\n        s += "."\n    return out + "|" + s\n\n'
     'print(scan("abcdefghijklmnop"))\nprint(grow("abc"))\n'
     's = "abcdefghijklmnop"\nout = ""\nfor c in s:\n    out += c\n'
     '    s = s + "x"\nprint(out, len(s))\n'),
    # --- `del xs[i]` boxed the list and ran dict_pop on the copy: SIGSEGV
    ("delete_list_elements",
     "xs: list[int] = [1, 2, 3, 4, 5]\ndel xs[0]\nprint(xs, len(xs))\n"
     "del xs[-1]\nprint(xs)\nys = ['a', 'b', 'c']\ndel ys[1]\n"
     "print(ys, len(ys))\nzs: list[str] = ['p', 'q', 'r']\ndel zs[0]\nprint(zs)\n"),
    # --- dict == compared boxes; the answer was always False
    ("dict_equality_by_content",
     "a = {1: 2, 3: 4}\nb = {3: 4, 1: 2}\nc = {1: 2}\n"
     "print(a == b, a == c, a != c, {} == {})\n"
     "x: dict[int, int] = {1: 2}\ny: dict[int, int] = {1: 2}\n"
     "z: dict[int, int] = {1: 3}\nprint(x == y, x == z, x != z)\n"
     "print({'k': [1, 2]} == {'k': [1, 2]}, {'k': [1]} == {'k': [2]})\n"),
    # --- `s += rhs` evaluated a call on the right twice
    ("aug_assign_evaluates_rhs_once",
     "n = [0]\ndef side(n: list) -> str:\n    n[0] += 1\n    return 'x'\n\n"
     "s = 'a'\ns += side(n)\nprint(s, n[0])\n"),
    # --- a comprehension with a tuple target skipped the binding: after a
    # `for n, s in rows` loop it answered [2, 2]
    ("comprehension_tuple_targets",
     'rows = [[1, "a"], [2, "b"], [3, "c"]]\nfor n, s in rows:\n    pass\n'
     "r = [n for n, s in rows]\nq = [s for n, s in rows]\n"
     "t = [n * 10 for n, s in rows if n != 2]\nprint(r, q, t, n, s)\n"
     "grid = [[1, 2], [3, 4]]\nprint([a + b for a, b in grid])\n"),
    ("comprehension_restores_shadowed_name",
     '# a dynamic and a typed (str / int / float) shadow alike\n'
     'xs: list = ["a", "b"]\nx = xs[0]\ny = [x for x in xs]\nprint(y, x)\n'
     'names = ["a", "bb", "ccc"]\nx = names[0]\nzs = [x for x in names]\n'
     'print(zs, x, len(x))\nnums: list[int] = [3, 4, 5]\nn = 0\n'
     'ns = [n for n in nums]\nrs = [n for n in range(3)]\nprint(ns, rs, n)\n'
     'fs: list[float] = [1.5, 2.5]\nf = 0.5\ngs = [f for f in fs]\nprint(gs, f)\n'
     'rows = [[1, 2], [3, 4]]\nm = [[a for a in r] for r in rows]\nprint(m)\n'),
    # --- a str-valued dict's entry is the DICT'S buffer: `x = d[k]` then
    # `x += "!"` wrote into the dict, and a get/setdefault left as a
    # statement freed the dict's own value
    ("str_valued_dict_reads_are_copies",
     'd: dict[str, str] = {"k": "ab"}\nx = d["k"]\nx += "cd"\nprint(d["k"], x)\n'
     'd.setdefault("k", "new")\nd.get("k")\nd.setdefault("z", "zz")\n'
     'print(d["k"], d["z"], len(d))\nv = "ab"\nd["v"] = v\nv += "!"\n'
     'print(d["v"], v)\ny = d.pop("k")\nd["k"] = "new"\ny += "!"\n'
     'print(y, d["k"])\nprint(d)\n'),
    ("str_valued_dict_as_parameter",
     "def get(m: dict[str, str], k: str) -> str:\n    return m[k]\n\n"
     "def put(m: dict[str, str], k: str, v: str) -> int:\n    m[k] = v\n"
     "    return 0\n\nd: dict[str, str] = {'a': 'xx'}\nr = get(d, 'a')\n"
     'r += "!"\nput(d, "b", "yy")\nw = "zz"\nput(d, "c", w)\nw += "!!"\n'
     'print(r, d["a"], d["b"], d["c"], w)\n'),
]

# CPython has no implicit record constructor, so these Silu programs are
# compared against the reference interpreter instead (class records are a
# Silu construct; the interpreter is the oracle behind `silu verify`).
MATCH_INTERPRETER = [
    ("constructor_keyword_arguments",
     "class P:\n    x: int = 0\n    y: int = 0\n"
     "p = P(y=5)\nq = P(y=1, x=2)\nr = P(7)\nprint(p.x, p.y, q.x, q.y, r.x, r.y)\n"),
    ("typed_list_count_index",
     "li: list[int] = [1, 2, 2, 3]\nprint(li.count(2), li.index(3))\n"),
    # `h.n = 5` at module level crashed the self-hosted FRONT END
    ("module_level_field_store",
     "class H:\n    n: int\n\nh = H(1)\nh.n = 5\nprint(h.n)\n"
     "class P:\n    x: int\n    name: str\n\np = P(1, 'a')\np.x = 7\n"
     "p.name = 'bee'\nprint(p.x, p.name)\n"),
]

# (id, source, stdout before the failure, message fragment). CPython
# either succeeds or raises: these are the DOCUMENTED divergences of the
# language (i64 integers, no float result from an int pow) and a Python
# exception - the contract is the loud, non-zero, explained exit.
MUST_PANIC = [
    ("pow_overflow_panics",
     "a = 10\nb = 40\nprint('before')\nprint(a ** b)\n",
     "before\n", "OverflowError"),
    ("pow_negative_exponent_is_an_error",
     "a = 2\nb = -1\nprint('before')\nprint(a ** b)\n",
     "before\n", "int pow with negative exponent"),
    ("range_zero_step_runtime",
     "z = 0\nfor i in range(0, 5, z):\n    print(i)\n",
     "", "range() arg 3 must not be zero"),
    ("typed_list_index_miss_panics",
     "li: list[int] = [1, 2]\nprint('before')\nprint(li.index(9))\n",
     "before\n", "ValueError"),
    ("tuple_unpack_arity_runtime",
     "a, b = [1, 2, 3]\n", "", "ValueError"),
    ("count_on_a_non_container",
     "d = 5\nprint(d.count(1))\n", "", "TypeError"),
    # --- mutating a dict or set under its own loop is a RuntimeError in
    # CPython. The compiled planes walked a stale snapshot (dynamic) or
    # freed arrays (typed). The check sits at the loop head, before the
    # bound test, so a mutation in the LAST body still raises
    ("typed_dict_insert_under_loop",
     "d: dict[int, int] = {1: 1, 2: 2}\nfor k in d:\n    d[k + 10] = k\n"
     "print('done')\n", "", "RuntimeError: dictionary changed size during iteration"),
    ("typed_dict_delete_under_loop",
     "d: dict[int, int] = {1: 1, 2: 2}\nfor k in d:\n    del d[k]\n"
     "print('done')\n", "", "RuntimeError: dictionary changed size during iteration"),
    ("dict_pop_in_last_body",
     "d: dict[int, int] = {1: 1}\nfor k in d:\n    d.pop(k)\nprint('done')\n",
     "", "RuntimeError: dictionary changed size"),
    ("dynamic_dict_insert_under_loop",
     "d: dict = {1: 1, 2: 2}\nfor k in d:\n    d[k + 10] = k\nprint('done')\n",
     "", "RuntimeError: dictionary changed size"),
    ("dynamic_dict_items_delete_under_loop",
     "d: dict = {1: 1, 2: 2}\nfor k, v in d.items():\n    print(k, v)\n"
     "    del d[k]\nprint('done')\n",
     "1 1\n", "RuntimeError: dictionary changed size"),
    ("set_insert_under_loop",
     "s = {1, 2, 3}\nfor x in s:\n    s.add(10)\nprint('done')\n",
     "", "RuntimeError: dictionary changed size"),
    # DOCUMENTED stricter divergence: CPython only compares the size, so a
    # delete paired with an insert runs on (its own docs allow "fail to
    # iterate over all entries"); Silu refuses any structural change
    ("dict_churn_under_loop",
     "d: dict[int, int] = {1: 1, 2: 2, 3: 3}\nfor k in d:\n    del d[k]\n"
     "    d[k + 10] = k\nprint('done')\n",
     "", "RuntimeError: dictionary modified during iteration"),
    # --- shift counts and float -> int at run time: LLVM makes both poison
    ("shift_count_out_of_range",
     "n = 65\nprint('before')\nprint(1 << n)\n", "before\n", "OverflowError"),
    ("shift_count_negative",
     "n = -1\nprint('before')\nprint(1 >> n)\n", "before\n", "ValueError"),
    ("int_of_huge_float",
     "x = 1e300 * 10.0\nprint('before')\nprint(int(x))\n",
     "before\n", "OverflowError"),
]

# (id, source, text that must appear in the build error)
MUST_REJECT = [
    ("range_no_args", "for i in range():\n    print(i)\n",
     "range() takes 1 to 3 arguments"),
    ("range_four_args", "for i in range(1, 2, 3, 4):\n    print(i)\n",
     "range() takes 1 to 3 arguments"),
    ("range_zero_step_literal", "for i in range(0, 10, 0):\n    print(i)\n",
     "range() arg 3 must not be zero"),
    ("range_as_value_non_literal", "n = 10\nprint(len(range(n)))\n",
     "range(...) as a value"),
    ("bare_range_object", "r = range(5)\nprint(r)\n",
     "range(...) as a value"),
    ("range_membership", "print(3 in range(10))\n", "range(...) as a value"),
    ("tuple_unpack_arity", "a, b = 1, 2, 3\n", "3 values into 2 targets"),
    ("container_method_on_str_append", "s = 'ab'\nprint(s.append('c'))\n",
     "is not supported on str"),
    ("container_method_on_str_get", "s = 'ab'\nprint(s.get('a'))\n",
     "is not supported on str"),
    ("str_count_arity", "s = 'ab'\nprint(s.count())\n",
     "str.count() takes exactly one argument"),
    ("typed_list_unsupported_method", "li: list[int] = [1, 2]\nli.sort()\n",
     "is not supported on rawlist_i64"),
    # --- calls: every one of these used to compile into a different
    # program than the one written
    ("kwargs_duplicate_value",
     "def f(a: int, b: int) -> int:\n    return a + b\n\nprint(f(1, b=2, a=3))\n",
     "multiple values for argument"),
    ("kwargs_missing_argument",
     "def f(a: int, b: int) -> int:\n    return a + b\n\nprint(f(a=1))\n",
     "missing 1 required argument"),
    ("kwargs_unexpected_name",
     "def f(a: int, b: int) -> int:\n    return a + b\n\nprint(f(a=1, z=2))\n",
     "unexpected keyword argument 'z'"),
    ("kwargs_on_builtin", "print(len(1, key=2))\n",
     "keyword arguments are not supported"),
    ("kwargs_on_method_call", "l = [1, 2]\nprint(l.index(1, start=0))\n",
     "not supported for method calls"),
    ("static_call_too_few_args",
     "def f(a: int) -> int:\n    return a\n\nprint(f())\n",
     "call to 'f' with 0 args (expected 1)"),
    ("static_call_too_many_args",
     "def f(a: int) -> int:\n    return a\n\nprint(f(1, 2))\n",
     "call to 'f' with 2 args (expected 1)"),
    ("builtin_wrong_arity", "print(len(1, 2))\n",
     "len() takes 1 argument(s) (2 given)"),
    ("builtin_wrong_arity_zero", "print(len())\n",
     "len() takes 1 argument(s) (0 given)"),
    ("print_unknown_keyword", "print('a', file=None)\n",
     "does not support the keyword argument 'file'"),
    ("print_non_literal_separator", "n = '-'\nprint('a', 'b', sep=n)\n",
     "takes a string literal"),
    # --- constructs the self-hosted and Rust front ends reject at parse
    # time; the Python plane parsed them and dropped the meaning
    ("default_parameter_value",
     "def f(a: int, b: int = 5) -> int:\n    return a + b\n\nprint(f(1), f(1, 2))\n",
     "default parameter values are not part of Silu"),
    ("lambda_default_value", "g = lambda x, y=1: x + y\n",
     "default parameter values are not part of Silu"),
    ("star_args", "def g(*args) -> int:\n    return 0\n",
     "default parameter values are not part of Silu"),
    ("for_else",
     "for i in range(2):\n    pass\nelse:\n    print('else ran')\n",
     "'else' on a for loop is not part of Silu"),
    ("while_else",
     "i = 0\nwhile i < 1:\n    i += 1\nelse:\n    print('while else')\n",
     "'else' on a while loop is not part of Silu"),
    # --- a name assigned later in a function is local to the whole
    # function (Python's UnboundLocalError); the converter used to die
    # with a bare KeyError('x')
    ("read_before_local_assignment",
     "x = 1\ndef f() -> int:\n    y = x\n    x = 2\n    return y + x\n\n"
     "print(f(), x)\n", "is read before it is assigned"),
    # --- one loop variable, two kinds: `for k in int_dict` followed by
    # `for k in str_dict` read the string as an integer, silently
    ("loop_variable_reused_across_key_kinds",
     "d: dict[int, int] = {1: 2}\ne: dict[str, int] = {'a': 1}\n"
     "n = 0\nfor k in d:\n    n += 1\n"
     "for k in e:\n    n += len(k)\nprint(n)\n",
     "the key of this dict is str"),
    # --- a comprehension target may shadow a typed slot only with
    # elements of that slot's kind (a typed list says what they are);
    # unboxing anything else read the box with the wrong tag: [1, 1]
    ("comprehension_shadows_typed_variable",
     "x = 5\nxs = ['a', 'b']\ny = [x for x in xs]\nprint(y, x)\n",
     "shadows a i64 variable and the elements are not of that kind"),
    ("comprehension_typed_slot_from_dynamic_elements",
     "def f(s: str, items: list) -> list:\n    return [s for s in items]\n"
     "print(f('o', []))\n",
     "shadows a rawstr variable and the elements are not of that kind"),
]


@pytest.mark.parametrize("plane", PLANES)
@pytest.mark.parametrize("name,src", MATCH_CPYTHON, ids=[c[0] for c in MATCH_CPYTHON])
def test_compiled_matches_cpython(plane, name, src):
    rc, out = _plane(plane)(src)
    assert rc is not None, out  # build error
    crc, cout = _cpython(src)
    assert crc == 0, "case must be valid, succeeding CPython"
    assert (rc, out) == (crc, cout)


@pytest.mark.parametrize("plane", PLANES)
@pytest.mark.parametrize("name,src,text", MUST_REJECT,
                         ids=[c[0] for c in MUST_REJECT])
def test_unsupported_construct_is_a_compile_error(plane, name, src, text):
    rc, message = _plane(plane)(src)
    assert rc is None, "compiled instead of being rejected"
    assert text in message, message


@pytest.mark.parametrize("plane", PLANES)
@pytest.mark.parametrize("name,src,before,text", MUST_PANIC,
                         ids=[c[0] for c in MUST_PANIC])
def test_documented_divergence_panics_loudly(plane, name, src, before, text):
    rc, out = _plane(plane)(src)
    assert rc is not None, out  # build error
    assert rc != 0 and out.startswith(before), out
    assert text in out[len(before):], out


@pytest.mark.parametrize("plane", PLANES)
@pytest.mark.parametrize("name,src", MATCH_INTERPRETER,
                         ids=[c[0] for c in MATCH_INTERPRETER])
def test_compiled_matches_interpreter(plane, name, src):
    rc, out = _plane(plane)(src)
    assert rc is not None, out  # build error
    irc, iout = _interp(src)
    assert irc == 0 and out == iout


@pytest.mark.parametrize("name,src", MATCH_CPYTHON, ids=[c[0] for c in MATCH_CPYTHON])
def test_interpreter_agrees_too(name, src):
    """The reference interpreter is the oracle behind `silu verify` and
    `silu prove`; it used to answer for a program in isolation."""
    rc, out = _build_and_run(src)
    assert rc is not None, src
    assert out == _interp(src)[1]
