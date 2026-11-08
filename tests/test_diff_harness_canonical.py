"""diff_harness._canonical_ll: host-independent ll comparison.

The rust converter embeds a const_prefix.ll extracted on one build
host; the self-hosted converter emits the target triple/datalayout of
whatever machine IT runs on. Those two lines are environment, not
converter semantics - the gate normalizes them (plus the trailing
newline) so `ll conv rustconv` runs portably instead of failing at
byte 97 on any other host.
"""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "diff_harness",
    os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "reference", "diff_harness.py"))
dh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dh)


def _ll(triple, layout):
    return (
        b'; ModuleID = "silu_module"\n'
        b'target triple = "' + triple + b'"\n'
        b'target datalayout = "' + layout + b'"\n'
        b"\n"
        b'define i32 @"main"()\n{\nret i32 0\n}\n'
    )


def test_triple_and_datalayout_normalized():
    mac = _ll(b"arm64-apple-darwin24.6.0", b"e-m:o-i64:64-i128:128-n32:64-S128")
    linux = _ll(b"x86_64-unknown-linux-gnu", b"e-m:e-p270:32:32-p271:32:32")
    assert dh._canonical_ll(mac) == dh._canonical_ll(linux)
    assert b"target triple = <host>" in dh._canonical_ll(mac)
    assert b"target datalayout = <host>" in dh._canonical_ll(mac)


def test_real_lines_outside_header_untouched():
    # a line that merely CONTAINS the words must not be touched
    raw = b'  %".1" = call i64 @"f"(i8* getelementptr inbounds '
    b'[7 x i8], [7 x i8]* @"str.target_20triple_20test", i32 0, i32 0)\n'
    assert dh._canonical_ll(raw) == raw.rstrip(b"\n")


def test_trailing_newline_normalized():
    assert dh._canonical_ll(b"x\n") == dh._canonical_ll(b"x")
