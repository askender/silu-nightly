#!/usr/bin/env python3
"""Differential harness for the Silu compiler planes.

A plane is a command that turns a .si source into a comparable artifact
(IR JSON or full .ll text). The harness runs two planes over the parity
corpus and reports per-file PASS/DIFF. Exit 1 on any DIFF.

Predates the Rust implementation: self-validation mode compares the two
EXISTING planes, which the CI gates already hold byte-identical - if
this harness reports DIFF there, the harness is broken, not the planes.

Usage:
    python reference/diff_harness.py ir fe pyir      # IR JSON planes
    python reference/diff_harness.py ll conv pyll    # full .ll planes
    python reference/diff_harness.py ir fe rustfe    # once R1 lands
"""

import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

CORPUS_IR = [
    *[os.path.join("benchmarks", f) for f in sorted(
        f for f in os.listdir(os.path.join(REPO, "benchmarks"))
        if f.endswith(".si"))],
    "selfhost/calc.si",
    "selfhost/ir_interp.si",
    "selfhost/silu_fe.si",
    "selfhost/typed_codegen_flat.si",
]
# the flat converter .ll round-trip through the python plane is minutes;
# IR parity on it is enough, .ll parity covers the other 18
CORPUS_LL = [f for f in CORPUS_IR if "typed_codegen_flat" not in f]


def _run(cmd, stdin_path=None, cwd=REPO, timeout=1200):
    stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    try:
        r = subprocess.run(cmd, stdin=stdin, capture_output=True,
                           cwd=cwd, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    finally:
        if stdin_path:
            stdin.close()


def plane_fe(rel):
    """Self-hosted front end: siluc1's fe half, binary `silu_fe`."""
    rc, out, err = _run([os.path.join(REPO, "silu_fe")],
                        stdin_path=os.path.join(REPO, rel),
                        cwd=os.path.dirname(os.path.join(REPO, rel)))
    return rc, out, err


def plane_pyir(rel):
    """Python-plane IR: silu ir --format json."""
    return _run([PY, "-m", "silu", "ir", os.path.join(REPO, rel),
                 "--format", "json"])


def plane_conv(rel):
    """Self-hosted converter monolith: full .ll on stdout."""
    return _run([os.path.join(REPO, "siluc1")],
                stdin_path=os.path.join(REPO, rel),
                cwd=os.path.dirname(os.path.join(REPO, rel)))


def plane_pyll(rel):
    """Python-plane converter: ir json -> llvm, full .ll."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as h:
        irf = h.name
    try:
        rc, out, err = _run([PY, "-m", "silu", "ir",
                             os.path.join(REPO, rel), "-o", irf])
        if rc != 0:
            return rc, b"", err
        return _run([PY, "-m", "silu", "llvm", irf])
    finally:
        os.unlink(irf)


def plane_rustfe(rel):
    """R1: Rust front end. Binary built by `cargo build -p silu-rs`."""
    return _run([os.path.join(REPO, "reference", "rust", "target",
                              "debug", "silu-fe"), rel])


def plane_rustconv(rel):
    """R2: Rust converter (embedded runtime prefix)."""
    return _run([os.path.join(REPO, "reference", "rust", "target",
                              "debug", "silu-conv"), rel])


PLANES = {
    "fe": plane_fe, "pyir": plane_pyir,
    "conv": plane_conv, "pyll": plane_pyll,
    "rustfe": plane_rustfe, "rustconv": plane_rustconv,
}


def _canonical_ir(raw):
    """IR planes serialize differently (silu_fe compact, python indented);
    the comparable artifact is the JSON VALUE in canonical form."""
    import json
    return json.dumps(json.loads(raw), separators=(",", ":"),
                      ensure_ascii=False).encode()


def _canonical_ll(raw):
    """LL planes may be built on different hosts: the target triple and
    datalayout come from the HOST llvmlite at build time (the embedded
    const_prefix.ll was extracted on an arm64 mac - on a linux CI host
    conv emits linux lines there), they are environment, not converter
    semantics. Normalize both lines plus the trailing newline so the
    gate runs portably."""
    out = []
    for line in raw.split(b"\n"):
        if (line.startswith(b"target triple = ")
                or line.startswith(b"target datalayout = ")):
            out.append(line.split(b" = ", 1)[0] + b" = <host>")
        else:
            out.append(line)
    return b"\n".join(out).rstrip(b"\n")


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("ir", "ll"):
        print(__doc__)
        return 2
    mode, a_name, b_name = sys.argv[1], sys.argv[2], sys.argv[3]
    a, b = PLANES[a_name], PLANES[b_name]
    corpus = CORPUS_IR if mode == "ir" else CORPUS_LL
    fails = 0
    for rel in corpus:
        t0 = time.time()
        arc, aout, aerr = a(rel)
        brc, bout, berr = b(rel)
        if mode == "ir" and arc == 0 and brc == 0:
            aout, bout = _canonical_ir(aout), _canonical_ir(bout)
        if mode == "ll" and arc == 0 and brc == 0:
            # the python serializer appends one trailing newline the
            # self-hosted one does not; triple/datalayout come from the
            # build host's llvmlite - neither is converter semantics
            aout, bout = _canonical_ll(aout), _canonical_ll(bout)
        dt = time.time() - t0
        if arc != 0 or brc != 0:
            print(f"ERROR {rel} ({dt:.1f}s): plane rc {a_name}={arc} "
                  f"{b_name}={brc}")
            print(f"  {a_name} stderr: {aerr[:150]!r}")
            print(f"  {b_name} stderr: {berr[:150]!r}")
            fails += 1
        elif aout == bout:
            print(f"PASS  {rel} ({dt:.1f}s, {len(aout)} bytes)")
        else:
            print(f"DIFF  {rel} ({dt:.1f}s): {len(aout)} vs "
                  f"{len(bout)} bytes")
            for i, (x, y) in enumerate(zip(aout, bout)):
                if x != y:
                    print(f"  first diff at byte {i}: "
                          f"{aout[max(0,i-40):i+40]!r}\n  vs           "
                          f"{bout[max(0,i-40):i+40]!r}")
                    break
            fails += 1
    print(f"--- {a_name} vs {b_name} ({mode}): "
          f"{len(corpus) - fails}/{len(corpus)} identical ---")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
