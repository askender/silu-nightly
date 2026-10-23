"""Runtime boundary suite: container/str edge cases where the native
runtime historically diverged (list_insert capacity, set tag-8, dict
key routing, str slicing on promoted strings). Every case is checked
against the IR interpreter - the reference semantics.
"""

import pytest

from tests.test_str_builtins import run_ir, run_mcjit


def check(source: str) -> str:
    expected = run_ir(source)
    assert run_mcjit(source) == expected
    return expected


class TestListBoundaries:
    def test_insert_then_append_growth(self):
        """insert must fix capacity or the next append writes past
        the buffer (the #1 blocker of the whole campaign)."""
        check(
            "xs = []\n"
            "xs.insert(0, 1)\n"
            "xs.append(2)\n"
            "xs.append(3)\n"
            "print(xs)\nprint(len(xs))\n"
        )

    def test_insert_front_mid_end(self):
        check(
            "xs = [1, 3]\n"
            "xs.insert(1, 2)\n"
            "xs.insert(0, 0)\n"
            "xs.insert(len(xs), 4)\n"
            "print(xs)\n"
        )

    def test_insert_negative_and_clamp(self):
        check(
            "xs = [1, 2]\n"
            "xs.insert(-1, 9)\nprint(xs)\n"
            "ys = [1, 2]\nys.insert(99, 9)\nprint(ys)\n"
            "zs = [1, 2]\nzs.insert(-99, 9)\nprint(zs)\n"
        )

    def test_repeat_zero_empty_and_nested(self):
        check(
            "a = [1, 2] * 0\nprint(len(a))\n"
            "b = [1] * 3\nprint(b)\n"
            "c = [[1], [2]] * 2\nprint(c)\n"
        )

    def test_slice_on_promoted_str_list(self):
        check(
            's = "abcdef"\n'
            "print(s[2:])\nprint(s[:3])\nprint(s[1:4])\n"
            "print(s[-2:])\n"
        )

    def test_slice_on_rawlist(self):
        check(
            "xs: list[int] = [1, 2, 3, 4]\n"
            "ys = xs[1:]\n"
            "t = 0\n"
            "i = 0\n"
            "while i < len(ys):\n"
            "    t += ys[i]\n"
            "    i += 1\n"
            "print(t)\n"
        )


class TestSetBoundaries:
    def test_dedup_and_idempotent_add(self):
        check(
            "s = {1, 1, 2, 2, 3}\nprint(len(s))\n"
            "s.add(2)\nprint(len(s))\n"
            "s.add(4)\nprint(len(s))\n"
        )

    def test_update_from_tuple_and_dict_keys(self):
        check(
            "s = set()\n"
            "s.update((1, 2))\n"
            "s.update((2, 3))\n"
            "print(len(s))\nprint(1 in s)\nprint(3 in s)\n"
            "d = {'a': 1}\n"
            "t = set(d.keys())\nprint(len(t))\n"
        )

    def test_subset_superset_relations(self):
        check(
            "s = {1, 2}\n"
            "print(s <= {1, 2, 3})\n"
            "print(s < {1, 2})\n"
            "print(s < {1, 2, 3})\n"
            "print(s >= {1})\n"
            "print(s > {1, 2})\n"
            "print(s == {2, 1})\n"
            "print(s != {1})\n"
        )

    def test_empty_set_ctor_and_membership(self):
        check(
            "u = set()\nprint(len(u))\n"
            "u.add(1)\nprint(1 in u)\nprint(2 in u)\n"
        )


class TestDictBoundaries:
    def test_keys_values_items_projections(self):
        check(
            "d = {'a': 1, 'b': 2}\n"
            "print(len(list(d.keys())))\n"
            "print(len(list(d.values())))\n"
            "print(len(d.items()))\n"
            "print('a' in d.keys())\n"
        )

    def test_pop_copy_clear(self):
        check(
            "d = {'a': 1, 'b': 2}\n"
            "print(d.pop('a'))\nprint(len(d))\n"
            "c = d.copy()\nc['z'] = 9\nprint(len(d))\nprint(len(c))\n"
            "d.clear()\nprint(len(d))\n"
        )


class TestStrBoundaries:
    def test_empty_and_single(self):
        check(
            'print(len(""))\n'
            'print(""[0:0])\n'
            'print("a"[0])\n'
            'print("abc"[-1])\n'
        )

    def test_chained_comparisons(self):
        check(
            "a = 2\nprint(0 <= a < 3)\nprint(1 < 2 < 3 < 4)\n"
            "print(0 <= 5 < 3)\n"
            "b = [10, 20, 30]\nprint(0 <= a < len(b))\n"
        )

    def test_none_containers(self):
        check(
            "x = ['const', None]\n"
            "y = x[:2]\n"
            "print(y == ['const', None])\n"
            "print([1] != [1.0])\n"
            "print([True] == [1])\n"
        )
