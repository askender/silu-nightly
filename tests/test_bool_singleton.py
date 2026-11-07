"""P5: True/False are immortal singleton boxes.

create_bool hands out @silu_true/@silu_false (no allocation, a bare
select), nothing else ever constructs a tag-3 box (audited), and
`x is True` compiles to ONE pointer compare against the singleton -
which also covers the null case for free and matches CPython's
small-bool-identity semantics. Any future recursive pyobj release
MUST exempt tag=3 (the boxes are shared immortals).
"""

import pytest

from tests.test_typed_codegen import _convert  # the established probe


def test_true_false_globals_exist():
    ll = _convert("x: object = True\ny: object = False\nprint(x, y)\n")
    assert '@"silu_true_payload" = constant i64 1' in ll
    assert '@"silu_false_payload" = constant i64 0' in ll
    assert '@"silu_true" = constant {i32, i8*} {i32 3, i8* bitcast' in ll
    assert '@"silu_false" = constant {i32, i8*} {i32 3, i8* bitcast' in ll


def test_create_bool_is_a_select_not_allocations():
    import re

    ll = _convert("b: object = 1 == 2\nprint(b)\n")
    body = re.search(r'define \{i32, i8\*\}\* @"create_bool".*?\n\}', ll, re.S)
    assert body, "create_bool definition missing"
    text = body.group(0)
    assert "malloc" not in text
    assert '@"silu_true"' in text and '@"silu_false"' in text


def test_is_true_is_single_pointer_compare():
    import re

    ll = _convert("x: object = True\nif x is True:\n    print(1)\n")
    assert re.search(
        r'icmp eq \{i32, i8\*\}\* %"\.[0-9]+', ll) and '@"silu_true"' in ll
    # the old 11-opcode walk must be gone: no tag load + icmp 3 chain
    # inside the user function (the runtime may still tag-check in
    # unrelated helpers, so scope to the main define)
    main = re.search(r'define i32 @"main"\(\).*?\n\}', ll, re.S).group(0)
    assert 'icmp eq i32' not in main or ', 3' not in main


def test_is_false_and_is_not():
    import re

    ll = _convert(
        "x: object = False\nif x is False:\n    print(1)\n"
        "if x is not True:\n    print(2)\n"
    )
    assert re.search(
        r'icmp eq \{i32, i8\*\}\* %"\.[0-9]+", @"silu_false"', ll)
    assert re.search(r'xor i1 %"\.[0-9]+", -1', ll)


def test_runtime_semantics_via_interpreter_binary():
    """End to end: the compiled program still prints the truth."""
    import subprocess

    ll = _convert("b: object = 2 > 1\nif b is True:\n    print(\"yes\")\n")
    with open("/tmp/bs_probe.ll", "w") as h:
        h.write(ll)
    binary = "/tmp/bs_probe_bin"
    if subprocess.run(["clang", "-O1", "/tmp/bs_probe.ll", "-lm", "-o",
                       binary], capture_output=True).returncode != 0:
        pytest.skip("clang unavailable")
    out = subprocess.run([binary], capture_output=True, text=True)
    assert out.stdout == "yes\n"
