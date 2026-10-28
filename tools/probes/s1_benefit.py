#!/usr/bin/env python3
"""S1 benefit probe: mixed value-tree construction, pyobj vs tagged.

Uses the REAL emitted runtimes (not hand-rolled malloc shapes like
the S0 probe): the pyobj side builds JInt/JStr/JArr the way
jsonparse.si does today (create_int / create_str / create_list /
list_append / pyobj instance), the tagged side uses the S1 emitters
(tagged_new_scalar / tagged_new_ptr over rawlist). The mix mirrors
jsonparse's value distribution (int-heavy leaves, one small array
per three leaves).

Run:  python3 tools/probes/s1_benefit.py
"""

import subprocess
import sys
import time

sys.path.insert(0, ".")

N = 100000

PYOBJ_MAIN = f"""
define i32 @main() {{
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %body]
  %acc = phi i64 [0, %entry], [%acc2, %body]
  %done = icmp sge i64 %i, {N}
  br i1 %done, label %out, label %body
body:
  ; JInt: pyobj box (2 mallocs) + instance wrap
  %v1 = call {{i32, i8*}}* @"create_int"(i64 %i)
  ; JStr: pyobj str box over a constant rawstr
  %kbuf = getelementptr [2 x i8], [2 x i8]* @kk, i32 0, i32 0
  %s0 = call i8* @"rawstr_new_copy"(i8* %kbuf, i64 1)
  %v2 = call {{i32, i8*}}* @"create_str"(i8* %s0, i32 1)
  ; JArr: pyobj list + two appends
  %l0 = call {{i32, i8*}}* @"create_list"(i64 2)
  call {{i32, i8*}}* @"list_append"({{i32, i8*}}* %l0, {{i32, i8*}}* %v1)
  call {{i32, i8*}}* @"list_append"({{i32, i8*}}* %l0, {{i32, i8*}}* %v2)
  %p1 = ptrtoint {{i32, i8*}}* %v1 to i64
  ; instance wrap: fields array + pyobj_make_instance (the JX layer)
  %fa = call i8* @"malloc"(i64 8)
  %fab = bitcast i8* %fa to {{i32, i8*}}**
  store {{i32, i8*}}* %v1, {{i32, i8*}}** %fab
  %inst1 = call {{i32, i8*}}* @"pyobj_make_instance"(i64 1, i8* %fa)
  %slot = and i64 %i, 15
  %ge = getelementptr [16 x {{i32, i8*}}*], [16 x {{i32, i8*}}*]* @sink, i32 0, i64 %slot
  store {{i32, i8*}}* %l0, {{i32, i8*}}** %ge
  %acc2 = add i64 %acc, %p1
  %next = add i64 %i, 1
  br label %loop
out:
  %h = getelementptr [5 x i8], [5 x i8]* @fmt, i32 0, i32 0
  %pr = call i32 (i8*, ...) @printf(i8* %h, i64 %acc)
  ret i32 0
}}
@kk = private constant [2 x i8] c"k\\00"
@fmt = private constant [5 x i8] c"%ld\\0A\\00"
@sink = global [16 x {{i32, i8*}}*] zeroinitializer
"""

TAGGED_MAIN = f"""
define i32 @main() {{
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %body]
  %acc = phi i64 [0, %entry], [%acc2, %body]
  %done = icmp sge i64 %i, {N}
  br i1 %done, label %out, label %body
body:
  ; JInt: one 16-byte block
  %v1 = call i8* @"tagged_new_scalar"(i32 1, i64 %i)
  ; JStr: one block over the rawstr (tags: 1=int 2=str 5=list)
  %kbuf = getelementptr [2 x i8], [2 x i8]* @kk, i32 0, i32 0
  %s0 = call i8* @"rawstr_new_copy"(i8* %kbuf, i64 1)
  %v2 = call i8* @"tagged_new_ptr"(i32 2, i8* %s0)
  ; JArr: rawlist of block pointers + one block
  %l0 = call i8* @"rawlist_new"(i64 8)
  %b1 = ptrtoint i8* %v1 to i64
  %b2 = ptrtoint i8* %v2 to i64
  %p1 = call i64 @"rawlist_push"(i8* %l0, i64 %b1)
  %p2 = call i64 @"rawlist_push"(i8* %l0, i64 %b2)
  %lb = call i8* @"tagged_new_ptr"(i32 5, i8* %l0)
  %slot = and i64 %i, 15
  %ge = getelementptr [16 x i8*], [16 x i8*]* @sink, i32 0, i64 %slot
  store i8* %lb, i8** %ge
  %acc2 = add i64 %acc, %b1
  %next = add i64 %i, 1
  br label %loop
out:
  %h = getelementptr [5 x i8], [5 x i8]* @fmt, i32 0, i32 0
  %pr = call i32 (i8*, ...) @printf(i8* %h, i64 %acc)
  ret i32 0
}}
@kk = private constant [2 x i8] c"k\\00"
@fmt = private constant [5 x i8] c"%ld\\0A\\00"
@sink = global [16 x i8*] zeroinitializer
"""


def emit_module(extra_main: str) -> str:
    from silu.ir_iface import ir
    from silu.typed_codegen import TypedCodegen

    cg = TypedCodegen()
    cg._ensure_tagged_runtime()
    text = ir.module_str(cg.module)
    if '@"printf"' not in text:
        text = 'declare i32 @"printf"(i8*, ...)\n' + text
    return text + extra_main


def med(exe, n=9):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run([exe], capture_output=True)
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return ts[n // 2]


def main():
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as td:
        results = {}
        for name, m in (("pyobj", PYOBJ_MAIN), ("tagged", TAGGED_MAIN)):
            ll = os.path.join(td, name + ".ll")
            exe = os.path.join(td, name)
            open(ll, "w").write(emit_module(m))
            build = subprocess.run(["clang", "-O2", ll, "-o", exe],
                                   capture_output=True, text=True)
            assert build.returncode == 0, build.stderr[:600]
            r = subprocess.run([exe], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:200]
            results[name] = med(exe)
        pyobj, tagged = results["pyobj"], results["tagged"]
        per_p = (pyobj - 3.5) * 1e6 / (N * 3)
        per_t = (tagged - 3.5) * 1e6 / (N * 3)
        print(f"pyobj  : {pyobj:7.2f}ms  ~{per_p:5.0f}ns/值")
        print(f"tagged : {tagged:7.2f}ms  ~{per_t:5.0f}ns/值")
        print(f"构造比值 pyobj/tagged = {pyobj / tagged:.2f}x")


if __name__ == "__main__":
    main()
