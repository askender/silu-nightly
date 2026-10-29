"""Target and cache contracts for the split native build."""

from silu import runtime_cache


def test_split_preserves_actual_target_header():
    header = (
        '; ModuleID = "silu"\n'
        'target datalayout = "e-m:e-p:64:64-i64:64-n32:64-S128"\n'
        'target triple = "x86_64-pc-linux-gnu"\n\n'
    )
    runtime = header + 'define void @"rt"() {\nentry:\n  ret void\n}\n'
    full = runtime + '\ndefine i32 @"main"() {\nentry:\n  ret i32 0\n}\n'
    _, user = runtime_cache.split(full, rt_text=runtime)
    assert 'target triple = "x86_64-pc-linux-gnu"' in user
    assert "arm64-apple-darwin" not in user
    assert 'define i32 @"main"()' in user
