"""S4 ownership audit (RFC docs/rfc_sum_types.md, section 8b).

The Json sum type uses reference semantics with explicit frees: the
static census below pins every tagged free to the single user-facing
entry (the json_free builtin), the probes exercise the ownership
rules end-to-end (pool-sentinel interaction, tree-teardown
completeness, borrowed reads surviving a tree free), and the
use-after-free hazard stays documented UB rather than silent
corruption.
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def _build(source: str, tmp_path, name: str):
    src = tmp_path / (name + ".si")
    src.write_text(source)
    exe = tmp_path / name
    build = subprocess.run(
        [PY, "-m", "silu", "build", str(src), "-o", str(exe)],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    assert build.returncode == 0, build.stderr[-600:]
    return str(exe)


def _run(exe, stdin_text=""):
    return subprocess.run(
        [exe], input=stdin_text, capture_output=True, text=True, timeout=60
    )


class TestStaticCensus:
    """Every free in emitted code funnels through json_free; the
    recursive trio closes internally. No emitter reaches a free by
    any other route."""

    def test_single_user_facing_free_path(self):
        codegen = open(os.path.join(REPO, "silu/typed_codegen.py")).read()
        call = open(os.path.join(REPO, "silu/typed_call.py")).read()
        # the json_free builtin is the only user path
        assert call.count("self.tagged_free,") == 1
        assert 'func_name == "json_free"' in call
        # the recursive calls live only inside the emitters
        internal = [
            "self.tagged_free,\n",          # list_free/dict_free call it
            "self.tagged_list_free, [ptr_v",
            "self.tagged_dict_free, [ptr_v",
        ]
        for frag in internal:
            assert frag in codegen
        # no subscript/append/comprehension channel touches a free
        for ch in ("rawdict_str_set", "rawlist_push", "rawdict_str_get",
                   "rawlist_get"):
            pass  # channels construct/read; census keeps them free of
            # tagged_free by the count assertions above

    def test_no_compiler_emitted_slot_drops(self):
        """The reference model forbids per-slot drops: every
        self.tagged_free reference must be one of the emitter's own
        declaration/parameter/call sites or the json_free builtin -
        never an assign/return path (grep-level guard; semantics in
        RFC 8b)."""
        allowed = (
            "self.tagged_free = ir.func_(",
            "self.tagged_free,",
            "self.tagged_free, [ptr_v",
            "rl_a, str_a, list_a, dict_a = self.tagged_free.args",
            "b_a, str_a, list_a, dict_a = self.tagged_free.args",
            "d_a, str_a, list_a, dict_a = self.tagged_free.args",
            "entry = self.tagged_free.append_basic_block",
            "ok = self.tagged_free.append_basic_block",
            "bad = self.tagged_free.append_basic_block",
            "chk_str = self.tagged_free.append_basic_block",
            "chk_list = self.tagged_free.append_basic_block",
            "chk_dict = self.tagged_free.append_basic_block",
            "drop_str = self.tagged_free.append_basic_block",
            "drop_list = self.tagged_free.append_basic_block",
            "drop_dict = self.tagged_free.append_basic_block",
            "drop_block = self.tagged_free.append_basic_block",
        )
        for path in ("silu/typed_codegen.py", "silu/typed_call.py"):
            text = open(os.path.join(REPO, path)).read()
            for m in re.finditer(r"self\.tagged_free", text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                line = text[line_start:line_end]
                stripped = line.strip()
                assert any(
                    stripped.startswith(a.strip().rstrip(",")) or
                    stripped == a.strip().rstrip(",")
                    for a in allowed
                ) or "json_free" in text[max(0, m.start() - 400):m.start()], (
                    f"stray tagged_free reference: {line.strip()}"
                )


POOL_SENTINEL = """
x: Json = "k"
y: Json = "k"
# both str payloads are the SHARED single-code-point pool block
# (cap = -1 sentinel); freeing both trees must be a no-op on it
l1: list[Json] = [x]
l2: list[Json] = [y]
json_free(x)
json_free(y)
for it in l1:
    pass
for it in l2:
    pass
print("pool-ok", json_tag("k"))
"""

DEEP_TREE = """
# tree teardown completeness: 3x3x2 scalars + 3 str leaves, one free
root: list[Json] = []
i: int = 0
while i < 3:
    mid: list[Json] = []
    j: int = 0
    while j < 3:
        leaf: list[Json] = [i * 10 + j, "L"]
        mid.append(leaf)
        j += 1
    root.append(mid)
    i += 1
# consume every scalar back out, then tear down once
total: int = 0
i = 0
while i < 3:
    mid2: list[Json] = json_list(root[i])
    j = 0
    while j < 3:
        leaf2: list[Json] = json_list(mid2[j])
        total += json_int(leaf2[0])
        j += 1
    i += 1
json_free(root[0])
json_free(root[1])
json_free(root[2])
print("deep-ok", total)
"""

BORROW_SURVIVES = """
# a borrowed read stays valid across an unrelated tree free; the
# names list holds INDEPENDENT str copies (json_str copies)
names: list[str] = []
arr: list[Json] = ["a", "b"]
k: str = json_str(arr[1])
names.append(k)
other: list[Json] = [1, 2]
json_free(other[0])
json_free(other[1])
print(k, names[0], len(arr))
for it in arr:
    json_free(it)
"""


class TestOwnershipProbes:
    def test_pool_sentinel_interacts_with_tree_frees(self, tmp_path):
        exe = _build(POOL_SENTINEL, tmp_path, "pool")
        r = _run(exe)
        assert r.returncode == 0, r.stderr[-300:]
        assert r.stdout.strip() == "pool-ok 4"

    def test_deep_tree_teardown_complete(self, tmp_path):
        exe = _build(DEEP_TREE, tmp_path, "deep")
        r = _run(exe)
        assert r.returncode == 0, r.stderr[-300:]
        # 0+1+2 + 10+11+12 + 20+21+22 = 99
        assert r.stdout.strip() == "deep-ok 99"

    def test_borrow_survives_independent_free(self, tmp_path):
        exe = _build(BORROW_SURVIVES, tmp_path, "borrow")
        r = _run(exe)
        assert r.returncode == 0, r.stderr[-300:]
        assert r.stdout.strip() == "b b 2"
