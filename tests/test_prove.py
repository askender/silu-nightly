"""silu prove: Z3 panic-free proofs (roadmap Phase 2, v1).

v1 scope: division/modulo by zero, intra-procedural. SOUND IN THE
SAFETY DIRECTION: a reachable abort is always reported (with a Z3
witness); a guarded divide may be flagged spuriously (the executor
evaluates on the linear path - branch-forked rebindings are v2).
"""

import subprocess
import sys


from silu.verify import verify_source

REPO = "."
PY = sys.executable


def test_reachable_division_abort_with_witness():
    ok, rep = verify_source(
        "def f(x: int, y: int) -> int:\n    return 10 / x + 10 % y\n"
    )
    assert not ok
    text = "\n".join(rep)
    assert "division by zero" in text and "modulo by zero" in text
    assert "x=0" in text and "y=0" in text  # Z3 counterexamples


def test_provably_safe_divide():
    ok, rep = verify_source(
        "def safe_div(a: int, b: int) -> int:\n    return a / (b * b + 1)\n"
    )
    assert ok
    assert "proved safe" in rep[0]


def test_algebraically_zero_divisor():
    ok, rep = verify_source(
        "def risky(m: int, n: int) -> int:\n    return m / (n - n)\n"
    )
    assert not ok
    assert "division by zero" in rep[0]


def test_no_checked_operations():
    ok, rep = verify_source("def h(x: int) -> int:\n    return x + 1\n")
    assert ok
    assert "no checked operations" in rep[0]


def test_concrete_zero_divisor_is_definite():
    ok, rep = verify_source(
        "def d(x: int) -> int:\n    return x / 3 + 1 / 1\n"
    )
    assert ok  # concrete nonzero divisors: no obligations at all


def test_cli_exit_codes(tmp_path):
    safe = tmp_path / "safe.si"
    safe.write_text("def f(a: int, b: int) -> int:\n    return a / (b * b + 1)\n")
    r = subprocess.run([PY, "-m", "silu", "prove", str(safe)],
                       capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "proved safe" in r.stdout

    risky = tmp_path / "risky.si"
    risky.write_text("def f(x: int) -> int:\n    return 1 / x\n")
    r2 = subprocess.run([PY, "-m", "silu", "prove", str(risky)],
                        capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r2.returncode == 1
    assert "POSSIBLE ABORT" in r2.stdout


def test_guarded_divide_path_sensitive_v2():
    """v2: the x==0 branch rebinds x to 1 before the divide, and the
    x!=0 branch excludes zero by its path condition - the guard is
    now honored instead of conservatively flagged."""
    ok, rep = verify_source(
        "def g(x: int) -> int:\n    if x == 0:\n        x = 1\n    return 10 / x\n"
    )
    assert ok, rep
    assert "proved safe" in rep[0]


def test_guarded_divide_still_catches_real_zero():
    """path sensitivity must not OVER-suppress: an unguarded symbolic
    divide still reports with a witness."""
    ok, rep = verify_source("def f(x: int) -> int:\n    return 1 / x\n")
    assert not ok
    assert "x=0" in rep[0]


class TestV11BoundsAndKeys:
    """v1.1: subscript bounds (statically-known lengths) and literal
    KeyError obligations; assignments now evaluate their RHS (the
    stock AssignmentHandler only knew the C-style 4-tuple assign, so
    checked operations inside Silu assignments were invisible)."""

    def test_bounds_reachable_with_witness(self):
        ok, rep = verify_source(
            "def pick(i: int) -> int:\n    return [10, 20, 30][i]\n"
        )
        assert not ok
        assert "index out of range [0, 3)" in rep[0]
        assert "i=" in rep[0]

    def test_bounds_proved_safe_by_modulo(self):
        ok, rep = verify_source(
            "def safe_pick(i: int) -> int:\n    return [10, 20, 30][i % 3]\n"
        )
        assert ok and "proved safe" in rep[0]

    def test_literal_index_overflow(self):
        ok, _ = verify_source("def bad() -> int:\n    return [7][9]\n")
        assert not ok

    def test_empty_container_read(self):
        ok, _ = verify_source("def e() -> int:\n    return [][0]\n")
        assert not ok

    def test_keyerror_missing_literal_key(self):
        ok, rep = verify_source(
            'def k() -> int:\n    d: dict[str, int] = {"a": 1}\n    return d["b"]\n'
        )
        assert not ok
        assert "KeyError" in rep[0]

    def test_keyerror_present_key_ok(self):
        ok, _ = verify_source(
            'def k() -> int:\n    d: dict[str, int] = {"a": 1}\n    return d["a"]\n'
        )
        assert ok

    def test_division_inside_assignment_now_visible(self):
        """the assign pre-hook: t = a / b records the obligation."""
        ok, rep = verify_source(
            "def f(a: int, b: int) -> int:\n    t: int = a / b\n    return t\n"
        )
        assert not ok
        assert "division by zero" in rep[0]

    def test_division_inside_loop_body_visible(self):
        ok, rep = verify_source(
            "def f(a: int, b: int, n: int) -> int:\n"
            "    i: int = 0\n    while i < n:\n"
            "        t: int = a / b\n        i = i + 1\n    return 0\n"
        )
        assert not ok  # conservative (guard is loop-dependent); v2 refines

    def test_real_parser_function_proves_clean(self):
        """roadmap Phase 2 exit criterion material: the jsonparse
        scanner functions analyze without crashing and prove ok."""
        src = (
            "def digit_value(ch: str) -> int:\n"
            '    if ch == "0":\n        return 0\n'
            "    return ord(ch) - 48\n\n"
            "def parse_number(s: str, pos: list[int]) -> int:\n"
            "    n: int = 0\n"
            '    while pos[0] < len(s) and s[pos[0]] >= "0" and s[pos[0]] <= "9":\n'
            "        n = n * 10 + digit_value(s[pos[0]])\n"
            "        pos[0] += 1\n    return n\n"
        )
        ok, rep = verify_source(src)
        assert ok, rep


class TestContracts:
    """require() contracts: a function's proof stands alone under
    its DECLARED domain (never under caller narrowing - removing a
    caller never invalidates anything); call sites are separately
    checked to respect the domain."""

    def test_require_makes_division_safe_standalone(self):
        ok, rep = verify_source(
            "def safe_div(a: int, b: int) -> int:\n"
            "    require(b != 0)\n"
            "    return a / b\n"
        )
        assert ok, rep
        assert "proved safe" in rep[0]

    def test_caller_satisfying_contract_ok(self):
        ok, _ = verify_source(
            "def safe_div(a: int, b: int) -> int:\n"
            "    require(b != 0)\n"
            "    return a / b\n"
            "def caller(x: int) -> int:\n"
            "    return safe_div(10, x * x + 1)\n"
        )
        assert ok  # x*x+1 >= 1 > 0 always

    def test_caller_violating_contract_caught(self):
        ok, rep = verify_source(
            "def safe_div(a: int, b: int) -> int:\n"
            "    require(b != 0)\n"
            "    return a / b\n"
            "def caller(x: int) -> int:\n"
            "    return safe_div(10, x - x)\n"
        )
        assert not ok
        text = "\n".join(rep)
        assert "CONTRACT VIOLATION" in text and "safe_div" in text

    def test_spectral_with_contract_proves_clean(self):
        """the interprocedural story: spectral's a(i,j) genuinely
        divides by zero on unconstrained ints (i=-1,j=0) but its
        call sites only pass i,j >= 0 - the require declares that
        domain, a() proves safe STANDALONE, and the whole file goes
        green."""
        src = (
            "def a(i: int, j: int) -> float:\n"
            "    require(i >= 0 and j >= 0)\n"
            "    return 1.0 / ((i + j) * (i + j + 1) / 2 + i + 1)\n"
        )
        ok, rep = verify_source(src)
        assert ok, rep
        assert "proved safe" in rep[0]

    def test_no_caller_narrowing_function_stands_alone(self):
        """removing every caller leaves the function's proof intact:
        a() with require is safe regardless of who calls it. This is
        the modular-composition property the design chose contracts
        over call-site narrowing for."""
        with_caller = (
            "def f(x: int) -> int:\n    require(x > 0)\n    return 10 / x\n"
            "def g(y: int) -> int:\n    return f(y + 1)\n"
        )
        without_caller = "def f(x: int) -> int:\n    require(x > 0)\n    return 10 / x\n"
        ok1, rep1 = verify_source(with_caller)
        ok2, rep2 = verify_source(without_caller)
        # f proves identically in both; ok differs only by g's site
        assert "proved safe" in rep1[0] and "proved safe" in rep2[0]

    def test_require_concrete_false_is_definite_abort(self):
        ok, rep = verify_source(
            "def f(x: int) -> int:\n    require(0 != 0)\n    return x\n"
        )
        assert not ok
        assert "unsatisfiable" in rep[0] or "require(false)" in rep[0]

    def test_empty_domain_is_vacuously_safe(self):
        """require(x != x) declares an empty domain: under it no
        abort is reachable (vacuous truth). A symbolic-but-empty
        domain is handled by the solver when obligations exist."""
        ok, _ = verify_source(
            "def f(x: int) -> int:\n    require(x != x)\n    return x\n"
        )
        assert ok
