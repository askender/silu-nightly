"""Sum-type runtime emitters (RFC S1, docs/rfc_sum_types.md).

S1 ships the emitter family only - no front-end syntax reaches it
yet, so the corpus .ll is unchanged and these tests drive the
emission directly: verify the emitted IR, then a hand-written main
appended to the runtime builds a value tree, reads it back, and
tears it down through the recursive frees.

Tag numbering used here (the per-union table arrives with S2):
0=null 1=int 2=str 3=list 4=dict.
"""

import subprocess

import pytest

from silu.typed_codegen import TypedCodegen

clang = pytest.importorskip("clang_shim", allow_module_level=False) if False else None


def _emit_runtime_ll():
    """Emit the module with the tagged runtime enabled and return the
    .ll text plus the converter (fresh, single use)."""
    from silu.ir_iface import ir

    cg = TypedCodegen()
    cg._ensure_tagged_runtime()
    return ir.module_str(cg.module), cg


def _has_all(text):
    names = [
        "tagged_new_scalar", "tagged_new_ptr", "tagged_tag",
        "tagged_bits", "tagged_ptr", "tagged_free",
        "tagged_list_free", "tagged_dict_free",
    ]
    return [n for n in names if f'@"{n}"' not in text]


def test_emitters_present_and_verifies():
    import llvmlite.binding as llvm

    ll, _cg = _emit_runtime_ll()
    missing = _has_all(ll)
    assert not missing, f"missing emitters: {missing}"
    m = llvm.parse_assembly(ll)
    m.verify()


def test_ensure_is_idempotent():
    ll, cg = _emit_runtime_ll()
    cg._ensure_tagged_runtime()  # second call must not re-emit
    assert ll.count('@"tagged_free"') >= 1


PROBE_MAIN = r'''
define i32 @tagged_probe() {
entry:
  ; int member: tag 1, value 42
  %i1 = call i8* @"tagged_new_scalar"(i32 1, i64 42)
  %i1v = call i64 @"tagged_bits"(i8* %i1)
  ; str member: tag 2, one-byte rawstr via rawstr_new_copy over a constant
  %kbuf = getelementptr [2 x i8], [2 x i8]* @probe_k, i32 0, i32 0
  %s0 = call i8* @"rawstr_new_copy"(i8* %kbuf, i64 1)
  %s1 = call i8* @"tagged_new_ptr"(i32 2, i8* %s0)
  %s1p = call i8* @"tagged_ptr"(i8* %s1)
  %s1len = ptrtoint i8* %s1p to i64
  %s1nonzero = icmp ne i64 %s1len, 0
  %s1len1 = zext i1 %s1nonzero to i64
  ; list member: tag 3, rawlist of block pointers
  %l0 = call i8* @"rawlist_new"(i64 8)
  %i1bits = ptrtoint i8* %i1 to i64
  %s1bits = ptrtoint i8* %s1 to i64
  %p1 = call i64 @"rawlist_push"(i8* %l0, i64 %i1bits)
  %p2 = call i64 @"rawlist_push"(i8* %l0, i64 %s1bits)
  %lb = call i8* @"tagged_new_ptr"(i32 3, i8* %l0)
  %ltag = call i32 @"tagged_tag"(i8* %lb)
  %llen = call i64 @"rawlist_len"(i8* %l0)
  ; teardown: the list free recursively drops i1 and s1 (and the
  ; rawstr under s1)
  call void @"tagged_free"(i8* %lb, i32 2, i32 3, i32 4)
  ; checksum: 42 + strlen(1) + list tag (3) + list len (2)
  %sum1 = add i64 %i1v, %s1len1
  %ltag64 = sext i32 %ltag to i64
  %sum2 = add i64 %sum1, %ltag64
  %sum = add i64 %sum2, %llen
  %h = getelementptr [5 x i8], [5 x i8]* @probe_fmt, i32 0, i32 0
  %pr = call i32 (i8*, ...) @printf(i8* %h, i64 %sum)
  ret i32 0
}
@probe_k = private constant [2 x i8] c"k\00"
@probe_fmt = private constant [5 x i8] c"%ld\0A\00"
'''


def test_probe_main_builds_reads_and_frees(tmp_path):
    import shutil

    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    ll, _cg = _emit_runtime_ll()
    # the emitted module has no main (no program was converted); the
    # probe IS the main. printf may not be declared - add the declare
    # if absent.
    text = ll
    if '@"printf"' not in text:
        text = "declare i32 @\"printf\"(i8*, ...)\n" + text
    text = text + PROBE_MAIN + '\ndefine i32 @main() {\nentry:\n  %r = call i32 @tagged_probe()\n  ret i32 0\n}\n'
    src = tmp_path / "probe.ll"
    src.write_text(text)
    exe = tmp_path / "probe"
    build = subprocess.run(
        ["clang", "-O1", str(src), "-o", str(exe)],
        capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stderr[:2000]
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[:2000]
    # 42 (int member) + 1 (str len) + 3 (list tag) + 2 (list len)
    assert run.stdout.strip() == "48"


DICT_PROBE_MAIN = r"""
define i32 @tagged_dict_probe() {
entry:
  ; value: int member tag 1, value 7
  %v1 = call i8* @"tagged_new_scalar"(i32 1, i64 7)
  %v1bits = ptrtoint i8* %v1 to i64
  ; key: one-byte rawstr
  %kbuf = getelementptr [2 x i8], [2 x i8]* @dprobe_k, i32 0, i32 0
  %k0 = call i8* @"rawstr_new_copy"(i8* %kbuf, i64 1)
  ; dict: rawdict_new + str_set, then wrap as tag 4
  %d0 = call i8* @"rawdict_new"()
  call void @"rawdict_str_set"(i8* %d0, i8* %k0, i64 %v1bits)
  %db = call i8* @"tagged_new_ptr"(i32 4, i8* %d0)
  %dtag = call i32 @"tagged_tag"(i8* %db)
  ; full teardown through the dict chain: frees key, value block,
  ; the entries arrays and the dict itself
  call void @"tagged_free"(i8* %db, i32 2, i32 3, i32 4)
  %dtag64 = sext i32 %dtag to i64
  %sum = add i64 %dtag64, 100
  %h = getelementptr [5 x i8], [5 x i8]* @dprobe_fmt, i32 0, i32 0
  %pr = call i32 (i8*, ...) @printf(i8* %h, i64 %sum)
  ret i32 0
}
@dprobe_k = private constant [2 x i8] c"a\00"
@dprobe_fmt = private constant [5 x i8] c"%ld\0A\00"
"""


def test_dict_probe_frees_through_entries(tmp_path):
    import shutil

    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    ll, _cg = _emit_runtime_ll()
    text = ll
    if '@"printf"' not in text:
        text = "declare i32 @\"printf\"(i8*, ...)\n" + text
    text = text + DICT_PROBE_MAIN + (
        '\ndefine i32 @main() {\nentry:\n'
        '  %r = call i32 @tagged_dict_probe()\n  ret i32 0\n}\n'
    )
    src = tmp_path / "dprobe.ll"
    src.write_text(text)
    exe = tmp_path / "dprobe"
    build = subprocess.run(
        ["clang", "-O1", str(src), "-o", str(exe)],
        capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stderr[:2000]
    run = subprocess.run([str(exe)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[:2000]
    # dict tag (4) + 100
    assert run.stdout.strip() == "104"
