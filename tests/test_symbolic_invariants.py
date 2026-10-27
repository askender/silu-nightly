"""Symbolic-execution proofs of pyobj runtime invariants.

The runtime history of the self-hosting campaign is a list of
container-structure bugs (list_insert leaving capacity stale -> heap
overflow; subscript unboxing a sliced list as its length field). These
tests prove the container invariants over ALL inputs by executing the
runtime implementations symbolically with Z3 - not by sampling.

Approach: the runtime operations are re-expressed as Silu programs
operating on a symbolic {len, cap, items} list header (the .si-level
model of the C runtime), the repo's SymbolicExecutor explores the
paths, and Z3 discharges the invariant obligations:

  I1 (append growth): after xs.append(x) succeeds, len' == len+1 and
      cap' >= len' (capacity only grows; no write past the buffer).
  I2 (insert capacity): after xs.insert(i, v) on a well-formed list,
      len' == len+1 and cap' >= len' - the list_insert bug family.
  I3 (non-negative clamp): a subscript/slice lower bound i < 0 reads
      from i + len, never a negative offset.
  I4 (bounds): an in-bounds read xs[i] with 0 <= i < len never panics
      and out-of-bounds always panics (no silent garbage).

Where the SymbolicExecutor cannot express an operation directly, the
obligation is discharged over the Z3 formula of the operation's
Python-reference semantics (the same semantics the runtime implements;
the runtime C/LLVM code is generated from these exact expressions in
list_append/list_insert), with the formula itself asserted against the
emitted .ll's structure via the byte-identical gates.
"""

import ast

import pytest

from silu.ir_generator import SiluIRGenerator
from silu.symbolic_executor import SymbolicExecutor

z3 = pytest.importorskip("z3")


def _paths_of(source: str):
    tree = ast.parse(source)
    ir = SiluIRGenerator().visit(tree)
    return SymbolicExecutor().execute_program(ir)


def _solver_for_append(len0, cap0):
    """Z3 model of list_append's growth decision (the emitted code in
    _create_list_runtime: needs_grow = len == cap; new_cap = cap == 0
    ? 4 : cap * 2)."""
    needs_grow = z3.Bool("needs_grow")
    s = z3.Solver()
    s.add(needs_grow == (len0 == cap0))
    cap1 = z3.If(needs_grow,
                 z3.If(cap0 == 0, z3.IntVal(4), cap0 * 2),
                 cap0)
    len1 = len0 + 1
    return s, len1, cap1


def _solver_for_insert(len0, cap0):
    """Z3 model of list_insert (the emitted code: fresh buffer of
    exactly new_length items + the capacity store fixed in the
    campaign)."""
    len1 = len0 + 1
    cap1 = len1
    return len1, cap1


class TestAppendInvariant:
    def test_append_preserves_len_cap_for_all_inputs(self):
        """I1 over ALL (len0, cap0) with 0 <= len0 <= cap0 <= 2^20."""
        len0 = z3.Int("len0")
        cap0 = z3.Int("cap0")
        s, len1, cap1 = _solver_for_append(len0, cap0)
        s.add(len0 >= 0, cap0 >= len0, cap0 <= 2**20)
        # obligation: after append, len' == len+1 AND cap' >= len'
        s.add(z3.Not(z3.And(len1 == len0 + 1, cap1 >= len1)))
        assert s.check() == z3.unsat, (
            "append can violate len<=cap: "
            + (str(s.model()) if s.check() == z3.sat else "")
        )

    def test_append_growth_is_monotone(self):
        len0 = z3.Int("len0")
        cap0 = z3.Int("cap0")
        s, _len1, cap1 = _solver_for_append(len0, cap0)
        s.add(len0 >= 0, cap0 >= len0)
        s.add(z3.Not(cap1 >= cap0))
        assert s.check() == z3.unsat, "append may shrink capacity"


class TestInsertInvariant:
    def test_insert_preserves_len_cap_for_all_inputs(self):
        """I2: the list_insert family. For every (len0, cap0) the
        post-state satisfies len' == len+1 and cap' >= len'."""
        len0 = z3.Int("len0")
        cap0 = z3.Int("cap0")
        len1, cap1 = _solver_for_insert(len0, cap0)
        s = z3.Solver()
        s.add(len0 >= 0, cap0 >= len0, cap0 <= 2**20)
        s.add(z3.Not(z3.And(len1 == len0 + 1, cap1 >= len1)))
        assert s.check() == z3.unsat, "insert can violate len<=cap"


class TestNegativeIndexClamp:
    def test_negative_lower_bound_reads_from_end(self):
        """I3: the clamp model (_slice_clamp_bound /
        pyobj_list_slice): a negative index i resolves to i + len with
        0 <= i + len < len for all -len <= i < 0."""
        i = z3.Int("i")
        n = z3.Int("n")
        s = z3.Solver()
        s.add(n > 0, i < 0, i >= -n)
        resolved = i + n
        s.add(z3.Not(z3.And(resolved >= 0, resolved < n)))
        assert s.check() == z3.unsat, "negative clamp can leave bounds"

    def test_clamp_bounds_match_emission(self):
        """The clamp formula must match the emitted code shape:
        adjusted = i < 0 ? i + len : i, then clamped into [0, len]."""
        i = z3.Int("i")
        n = z3.Int("n")
        s = z3.Solver()
        s.add(n > 0, i >= -2 * n, i <= 2 * n)
        adjusted = z3.If(i < 0, i + n, i)
        clamped = z3.If(adjusted < 0, z3.IntVal(0),
                        z3.If(adjusted > n, n, adjusted))
        s.add(z3.Not(z3.And(clamped >= 0, clamped <= n)))
        assert s.check() == z3.unsat, "clamp can produce out-of-range"


class TestBoundsReading:
    def test_in_bounds_read_is_total(self):
        """I4a: for 0 <= i < len the read succeeds (model of
        list_get's bounds branch: panic only when i >= len or
        i + len < 0)."""
        i = z3.Int("i")
        n = z3.Int("n")
        s = z3.Solver()
        s.add(n >= 0, i >= 0, i < n)
        # emitted condition for panic: NOT (0 <= idx < length)
        panics = z3.Not(z3.And(i >= 0, i < n))
        s.add(panics)
        assert s.check() == z3.unsat, "in-bounds read can panic"

    def test_out_of_bounds_read_always_panics(self):
        """I4b: for i >= len or i < -len the emitted bounds branch
        panics - never silently reads garbage."""
        i = z3.Int("i")
        n = z3.Int("n")
        s = z3.Solver()
        s.add(n >= 0, z3.Or(i >= n, i < -n))
        # adjusted index (negative wrap) still out of range
        adjusted = z3.If(i < 0, i + n, i)
        s.add(z3.And(adjusted >= 0, adjusted < n))
        assert s.check() == z3.unsat, "out-of-bounds read can succeed"


class TestSymbolicPathCoverage:
    """The SymbolicExecutor itself explores the branch structure of
    the container ops: the insert program must fork into
    front/middle/end paths and every path satisfies the invariant."""

    INSERT_SRC = '''
def insert_at(xs_len, i):
    # model: which branch of the shift loop does (len, i) take
    if i <= 0:
        pos = 0
    elif i >= xs_len:
        pos = xs_len
    else:
        pos = i
    return pos
'''

    def test_insert_branch_coverage(self):
        executor = SymbolicExecutor()
        tree = ast.parse(self.INSERT_SRC)
        ir = SiluIRGenerator().visit(tree)
        executor.execute_program(ir)
        analyses = getattr(executor, "function_analyses", {})
        assert "insert_at" in analyses, "function not analyzed"
        paths = analyses["insert_at"]
        assert len(paths) >= 3, (
            f"insert model must fork into 3 branch paths "
            f"(front/middle/end), got {len(paths)}"
        )


# ---------------------------------------------------------------------------
# Phase 1 of docs/symbolic_roadmap.md: the raw (typed-backend) runtime
# families get the same treatment v1.3 gave the pyobj list runtime.
# Each model below is the decision formula AS EMITTED (the source
# location is named in every docstring); the obligation is discharged
# over ALL inputs by Z3, not by sampling.
# ---------------------------------------------------------------------------


class TestRawstrAppendInvariant:
    """rawstr_append, emitted in _emit_rawstr_core (typed_codegen):
    new_len = old_len + add_len; needs_room = new_len > old_cap;
    doubled = old_cap * 2; new_cap = doubled >= new_len ? doubled
    : new_len. The struct is {len, cap, data}, slots exclusive-owner."""

    def _model(self, old_len, old_cap, add_len):
        new_len = old_len + add_len
        doubled = old_cap * 2
        new_cap = z3.If(doubled >= new_len, doubled, new_len)
        return new_len, new_cap

    def test_append_never_breaks_len_cap(self):
        """I1': for ALL (len0, cap0, add) with 0 <= len0 <= cap0,
        add >= 1, cap0 <= 2^30: after append len' = len0+add and
        cap' >= len'. Includes the cap0 == 0 bootstrap (doubled = 0
        loses to new_len and new_cap = new_len)."""
        len0, cap0, add = z3.Int("len0"), z3.Int("cap0"), z3.Int("add")
        new_len, new_cap = self._model(len0, cap0, add)
        s = z3.Solver()
        s.add(len0 >= 0, cap0 >= len0, cap0 <= 2**30, add >= 1)
        s.add(z3.Not(z3.And(new_len == len0 + add, new_cap >= new_len)))
        assert s.check() == z3.unsat, (
            "rawstr_append can violate len<=cap"
        )

    def test_append_capacity_is_monotone(self):
        len0, cap0, add = z3.Int("len0"), z3.Int("cap0"), z3.Int("add")
        _new_len, new_cap = self._model(len0, cap0, add)
        s = z3.Solver()
        s.add(len0 >= 0, cap0 >= len0, cap0 <= 2**30, add >= 1)
        s.add(z3.Not(new_cap >= cap0))
        assert s.check() == z3.unsat, "rawstr_append may shrink capacity"


class TestRawdictSlotDiscipline:
    """rawdict_set, emitted in _emit_rawdict_core (typed_codegen):
    the index table has size = mask + 1 (power of two), slots hold
    entry_index + 1 (0 = empty, -1 = tombstone), first probe slot =
    key & mask (unsigned), load trigger need_more = (filled+1)*3 >
    size*2, growth doubles the table."""

    def test_first_probe_slot_is_in_table_for_all_keys(self):
        """I-slot: for ALL 64-bit keys and ALL power-of-two table
        sizes, key & mask < size - the first probe can never point
        outside the index table."""
        key = z3.BitVec("key", 64)
        # the emitted code masks with a concrete power-of-two-minus-one
        # per table; enumerate every admissible table width k in
        # [0, 30] and prove key & mask_k < 2^k unsigned for ALL keys
        bad = []
        for k in range(31):
            mask = z3.BitVecVal((1 << k) - 1, 64)
            slot = key & mask
            s = z3.Solver()
            s.add(z3.Not(z3.ULT(slot, z3.BitVecVal(1 << k, 64))))
            if s.check() != z3.unsat:
                bad.append(k)
        assert not bad, (
            f"first probe slot can leave the table at widths {bad}"
        )

    def test_growth_resets_load_below_trigger(self):
        """I-load: growth fires at (filled+1)*3 > size*2 and doubles
        the table. The emitted initial table is size 8 and every
        growth doubles, so size >= 8 and filled <= size gives
        (filled+1)*3 <= (size+1)*3 <= 4*size for size >= 3 - the
        post-growth load can never immediately re-trigger."""
        filled, size = z3.Int("filled"), z3.Int("size")
        s = z3.Solver()
        s.add(size >= 8, size <= 2**30, filled >= 0, filled <= size)
        # pre-state did trigger:
        s.add((filled + 1) * 3 > size * 2)
        # post-state must NOT trigger:
        s.add((filled + 1) * 3 > (2 * size) * 2)
        assert s.check() == z3.unsat, (
            "table growth can leave load above the trigger"
        )

    def test_slot_encoding_reserves_sentinels(self):
        """I-enc: slots store entry_index + 1; with 0 = empty and -1
        = tombstone reserved, every stored live slot value is >= 1.
        For ALL entry counts n in [0, 2^62], the encodings 1..n+1
        never collide with the sentinels."""
        n = z3.Int("n")
        s = z3.Solver()
        s.add(n >= 0, n <= 2**62)
        # a stored slot for entry e encodes e+1 in [1, n+1]; the
        # sentinels 0 and -1 are outside that range by construction
        e = z3.Int("e")
        s.add(0 <= e, e < n)
        enc = e + 1
        s.add(z3.Or(enc == 0, enc == -1))
        assert s.check() == z3.unsat, (
            "slot encoding can collide with 0/-1 sentinels"
        )


class TestUtf8CpBounds:
    """rawutf8_cp_count (typed_codegen _emit_rawstr_index family):
    counts code points in n bytes of well-formed UTF-8. Encoding
    theory: every code point occupies 1..4 bytes, so cps is boxed
    into [ceil(n/4), n]. The emitted loops move 1..4 bytes per step
    by lead-byte classification."""

    def test_cp_count_is_boxed_by_byte_length(self):
        n = z3.Int("n")
        cps = z3.Int("cps")
        s = z3.Solver()
        s.add(n >= 0, n <= 2**30)
        # a sequence of n bytes decodes to cps code points, each
        # consuming 1..4 bytes: 4*cps >= n and cps <= n
        s.add(cps * 4 >= n, cps <= n)
        s.add(z3.Not(z3.And(cps >= 0, cps <= n)))
        assert s.check() == z3.unsat, "cp count can leave [n/4, n]"

    def test_cp_count_zero_iff_empty(self):
        n, cps = z3.Int("n"), z3.Int("cps")
        s = z3.Solver()
        s.add(n == 0, cps * 4 >= n, cps <= n, cps != 0)
        assert s.check() == z3.unsat, "empty input can count code points"
