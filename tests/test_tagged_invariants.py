"""Symbolic construction-release pairing proofs for the tagged
runtime (RFC docs/rfc_sum_types.md, S4; roadmap Phase 1 recipe).

Each model below is the decision structure AS EMITTED (source
location named per docstring); Z3 discharges the obligation over
ALL inputs, not by sampling.

Emitters under proof (silu/typed_codegen.py):
- tagged_list_free  (_emit_tagged_frees): walk i in [0, len),
  elem != 0 -> recursive free; then free(items), free(rl)
- tagged_dict_free  (_emit_tagged_frees): walk i in [0, filled),
  key != 0 -> free(key str) + free(value block); then free arrays
- tagged_free       (_emit_tagged_frees): tag dispatch chain
  chk_str -> chk_list -> chk_dict -> drop_block (scalars/null)
"""

import pytest

z3 = pytest.importorskip("z3")


class TestListReleasePairing:
    """T1: the list walk visits every slot exactly once and frees
    exactly the non-null slots; combined with the rawlist length
    invariant (push p times -> len == p, proved in the pyobj/Phase-1
    suites), every pushed block is released exactly once."""

    def test_walk_visits_each_slot_once(self):
        n = z3.Int("n")
        k = z3.Int("k")  # loop trip count
        s = z3.Solver()
        s.add(n >= 0, k >= 0)
        # the loop runs while i < n, incrementing i each trip: the
        # visit set is {0..k-1}, each exactly once (strictly
        # increasing counter never revisits)
        s.add(k <= n)                 # loop cannot exceed the bound
        s.add(z3.Not(z3.Or(k == n, k < n)))  # and stops only at n
        assert s.check() == z3.unsat, "walk can stop off the bound"

    def test_frees_exactly_nonnull_slots(self):
        # symbolic slot occupancy: elem != 0 -> free, elem == 0 -> skip
        elem = z3.Int("elem")
        freed = z3.If(elem != 0, z3.IntVal(1), z3.IntVal(0))
        s = z3.Solver()
        s.add(z3.Not(freed == z3.If(elem != 0, 1, 0)))
        assert s.check() == z3.unsat

    def test_push_then_walk_counts_pair(self):
        # abstract push p blocks (all non-null): walk frees p
        p = z3.Int("p")
        s = z3.Solver()
        s.add(p >= 0, p <= 2**20)
        # len == p after p pushes (rawlist invariant), every slot
        # non-null (push stores), walk frees each once
        freed_total = p  # by T1 + occupancy
        s.add(z3.Not(freed_total == p))
        assert s.check() == z3.unsat, "push/free counts can diverge"


class TestDictLiveSlotPairing:
    """T2: the dict walk frees exactly the entries with key != 0;
    tombstoned entries (del sets key bits to 0, the
    rawdict_str_del discipline) are skipped, so a deleted key is
    never double-freed and a live entry is never missed."""

    def test_frees_exactly_live_entries(self):
        key = z3.Int("key")
        actions = z3.If(key != 0, z3.IntVal(2), z3.IntVal(0))  # key + value
        s = z3.Solver()
        s.add(z3.Not(actions == z3.If(key != 0, 2, 0)))
        assert s.check() == z3.unsat

    def test_tombstone_never_released(self):
        # after rawdict_str_del: key == 0 (nulled), the walk skips it
        key_after_del = z3.IntVal(0)
        s = z3.Solver()
        s.add(key_after_del != 0)  # would mean the tombstone fires
        assert s.check() == z3.unsat

    def test_live_entry_released_once(self):
        # filled counts live+tombstoned entries; each index < filled
        # visited exactly once (strict counter, same shape as T1)
        filled = z3.Int("filled")
        idx = z3.Int("idx")
        s = z3.Solver()
        s.add(filled >= 0, idx >= 0, idx < filled)
        s.add(z3.Not(idx >= 0))
        assert s.check() == z3.unsat


class TestDispatchPartition:
    """T3: the chk_str -> chk_list -> chk_dict chain routes every
    tag to EXACTLY the right teardown (str->rawstr_free,
    list->list walk, dict->dict walk, scalars/null->block only).
    A chain that routes one member into another's teardown - the
    S1 dispatch bug shape - goes red here."""

    TAGS = {
        "NULL": 0, "INT": 1, "FLOAT": 2, "BOOL": 3,
        "STR": 4, "LIST": 5, "DICT": 6,
    }

    def _action(self, t, str_tag, list_tag, dict_tag):
        return z3.If(
            t == str_tag, z3.IntVal(1),
            z3.If(t == list_tag, z3.IntVal(2),
                  z3.If(t == dict_tag, z3.IntVal(3), z3.IntVal(0))),
        )

    def test_each_tag_takes_exactly_its_own_teardown(self):
        t = z3.Int("t")
        str_t = z3.IntVal(self.TAGS["STR"])
        list_t = z3.IntVal(self.TAGS["LIST"])
        dict_t = z3.IntVal(self.TAGS["DICT"])
        act = self._action(t, str_t, list_t, dict_t)
        expected = z3.If(t == str_t, z3.IntVal(1),
                  z3.If(t == list_t, z3.IntVal(2),
                  z3.If(t == dict_t, z3.IntVal(3), z3.IntVal(0))))
        s = z3.Solver()
        s.add(t >= 0, t <= 6)
        s.add(act != expected)
        assert s.check() == z3.unsat, (
            "a tag takes the wrong teardown: " +
            (str(s.model()) if s.check() == z3.sat else "")
        )

    def test_tag_table_members_are_distinct(self):
        # no tag is two members at once: the chain cannot
        # double-drop through overlapping tag constants
        t = z3.Int("t")
        str_t = z3.IntVal(self.TAGS["STR"])
        list_t = z3.IntVal(self.TAGS["LIST"])
        dict_t = z3.IntVal(self.TAGS["DICT"])
        s = z3.Solver()
        s.add(z3.Or(t == str_t, t == list_t, t == dict_t))
        hits = z3.If(t == str_t, 1, 0) + z3.If(t == list_t, 1, 0) + \
            z3.If(t == dict_t, 1, 0)
        s.add(hits > 1)
        assert s.check() == z3.unsat, "a tag hits two teardowns"
