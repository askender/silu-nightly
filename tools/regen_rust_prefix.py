#!/usr/bin/env python3
"""Regenerate the Rust oracle's embedded runtime prefix snapshots.

reference/rust/const_prefix.ll and tagged_prefix.ll are verbatim copies
of the runtime part of the .ll (the Rust converter emits `snapshot +
user functions`). They go stale whenever a runtime emitter changes and
the only symptom is `ll conv rustconv: 0/N identical`. The procedure
had lived as tribal knowledge with two documented traps (STATUS 3.33):
the snapshot must be taken from a FRESHLY rebuilt text-layer plane, and
it must end at a closing-brace newline (one extra blank line doubles
with the boundary the Rust emitter adds itself).

    python3 tools/regen_rust_prefix.py            # rewrite if changed
    python3 tools/regen_rust_prefix.py --check    # exit 1 if stale

Layout this enforces (reference/rust/src/bin/silu-conv.rs main):

    CONST_PREFIX ("}\\n") + "\\n" + [TAGGED_PREFIX ("}\\n") + "\\n"] + user fns

CONST is the common prefix of a plain program and a Json (tagged)
program; TAGGED is what two tagged programs share beyond CONST. A tiny
tagged probe is generated here so the second tagged sample always
exists (the corpus has exactly one Json program).
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SILUC1 = os.path.join(REPO, "siluc1")
CONST_PATH = os.path.join(REPO, "reference", "rust", "const_prefix.ll")
TAGGED_PATH = os.path.join(REPO, "reference", "rust", "tagged_prefix.ll")

PLAIN = [("fib", "benchmarks/fib.si"), ("dict", "benchmarks/dict.si")]
TAGGED_CORPUS = ("jsonparse_json", "benchmarks/jsonparse_json.si")
TAGGED_PROBE = (
    "tagprobe",
    'n: int = 3\nv: Json = json_int(n * 2)\nprint(json_tag(v), n)\n',
)


def _common(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return a[:i]


def _snap(text):
    """Truncate to the last closing-brace newline."""
    end = text.rfind("}\n")
    if end < 0:
        raise SystemExit("regen_rust_prefix: no '}\\n' boundary found")
    return text[:end + 2]


def _compile(src_path):
    with open(src_path, "rb") as h:
        r = subprocess.run([SILUC1], stdin=h, capture_output=True,
                           cwd=os.path.dirname(src_path), timeout=600)
    if r.returncode != 0 or not r.stdout:
        raise SystemExit(
            "regen_rust_prefix: siluc1 failed on %s: %r"
            % (src_path, (r.stdout + r.stderr)[:300]))
    return r.stdout.decode("utf-8", errors="replace")


def generate():
    # the text-layer plane must be newer than every converter source
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import selfhost_build as sb

    sb.ensure_siluc()
    plain = [_compile(os.path.join(REPO, rel)) for _, rel in PLAIN]
    tagged = [_compile(os.path.join(REPO, TAGGED_CORPUS[1]))]
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, "tagprobe.si")
        with open(probe, "w") as h:
            h.write(TAGGED_PROBE[1])
        tagged.append(_compile(probe))
    if not all("@\"tagged_" in t or "tagged" in t for t in tagged):
        raise SystemExit("regen_rust_prefix: a tagged sample has no tagged runtime")
    const = _snap(_common(plain[0], tagged[0]))
    for sample in plain[1:] + tagged[1:]:
        if _snap(_common(plain[0], sample)) != const:
            raise SystemExit("regen_rust_prefix: CONST prefix is not unique")
    shared = _common(tagged[0], tagged[1])
    if not shared.startswith(const + "\n"):
        raise SystemExit("regen_rust_prefix: tagged samples disagree on CONST")
    # the Rust emitter writes the CONST->TAGGED blank line itself
    tagged_prefix = _snap(shared[len(const) + 1:])
    for sample in plain:
        if not sample.startswith(const + "\n"):
            raise SystemExit("regen_rust_prefix: plain sample is not CONST + blank")
    for sample in tagged:
        if not sample.startswith(const + "\n" + tagged_prefix + "\n"):
            raise SystemExit("regen_rust_prefix: tagged sample layout mismatch")
    return const, tagged_prefix


def main():
    check = "--check" in sys.argv
    const, tagged_prefix = generate()
    old_const = open(CONST_PATH, errors="replace").read()
    old_tagged = open(TAGGED_PATH, errors="replace").read()
    changed = (const, tagged_prefix) != (old_const, old_tagged)
    if check:
        if changed:
            print("STALE: reference/rust prefix snapshots differ from the "
                  "text-layer plane (run tools/regen_rust_prefix.py)")
            return 1
        print("reference/rust prefix snapshots are current "
              "(const %d B, tagged %d B)" % (len(const), len(tagged_prefix)))
        return 0
    if not changed:
        print("reference/rust prefix snapshots unchanged "
              "(const %d B, tagged %d B)" % (len(const), len(tagged_prefix)))
        return 0
    for path, text in ((CONST_PATH, const), (TAGGED_PATH, tagged_prefix)):
        if open(path, errors="replace").read() != text:
            with open(path, "w") as h:
                h.write(text)
    print("rewrote reference/rust prefix snapshots: const %d -> %d B, "
          "tagged %d -> %d B" % (len(old_const), len(const),
                                 len(old_tagged), len(tagged_prefix)))
    print("next: cd reference/rust && cargo build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
