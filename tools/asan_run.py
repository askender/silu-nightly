#!/usr/bin/env python3
"""Real AddressSanitizer runs for compiled Silu programs.

clang instruments only the functions that carry the `sanitize_address`
attribute. A C translation unit gets it from clang's own front end; a
`.ll` input has none, so `clang -fsanitize=address x.ll` links the
runtime, registers the globals and checks NOTHING - and says nothing.
Every "asan clean" verdict this repo produced that way was vacuous: two
runtime walkers read one byte past every exact-size string buffer and
`s = s + s` read freed memory for weeks, and the compiler binary itself
crashed five times in one session.

    attributed(ll_text)              the module, every define tagged
    build(ll_text, workdir)          an ASan binary (AsanSetupError)
    run(binary, stdin)               AsanResult; kind None = quiet
    control()                        report kind for a KNOWN over-read

`control()` is the proof that this toolchain really reports one. A gate
built on this module calls it first and fails when it does not answer
"heap-buffer-overflow": a sanitizer that is silently not instrumenting
is worse than none, because it looks exactly like a clean program.
"""
import os
import subprocess
import tempfile
from collections import namedtuple

# leaks are by design (box buffers are never freed, the rawlist/rawdict
# buffers live for the process), and the macOS runtime symbolizer
# (atos) has hung for minutes on a report: symbolize afterwards if a
# stack is needed
ASAN_OPTIONS = "detect_leaks=0:symbolize=0"

# malloc(2), then read the third byte: the shape of the over-reads this
# module exists for
CONTROL_IR = """\
declare i8* @malloc(i64)
declare i32 @printf(i8*, ...)
@f = constant [4 x i8] c"%d\\0A\\00"
define i32 @main() {
  %p = call i8* @malloc(i64 2)
  store i8 97, i8* %p
  %p1 = getelementptr i8, i8* %p, i64 1
  store i8 98, i8* %p1
  %p2 = getelementptr i8, i8* %p, i64 2
  %v = load i8, i8* %p2
  %x = sext i8 %v to i32
  %r = call i32 (i8*, ...) @printf(i8* @f, i32 %x)
  ret i32 0
}
"""

AsanResult = namedtuple("AsanResult", "kind summary returncode stdout stderr")


class AsanSetupError(RuntimeError):
    """The sanitizer could not be built for this module."""


def attributed(ll_text):
    """The module with `sanitize_address` on every function definition.

    Both header layouts occur: llvmlite writes `define ... {`, the
    self-hosted text plane puts the brace on the next line."""
    out = []
    count = 0
    for line in ll_text.split("\n"):
        if line.startswith("define ") and line != "define ":
            if line.endswith("{"):
                line = line[:-1].rstrip() + " sanitize_address {"
            else:
                line = line + " sanitize_address"
            count += 1
        out.append(line)
    if count == 0:
        raise AsanSetupError("no function definition in the module")
    return "\n".join(out)


def build(ll_text, workdir):
    """Compile an attributed module to an ASan binary; returns its path."""
    ll_path = os.path.join(workdir, "p.asan.ll")
    binary = os.path.join(workdir, "p.asan")
    with open(ll_path, "w", encoding="utf-8") as h:
        h.write(attributed(ll_text))
    try:
        r = subprocess.run(
            ["clang", "-O1", "-fsanitize=address", "-fno-omit-frame-pointer",
             ll_path, "-lm", "-o", binary],
            capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsanSetupError("clang -fsanitize=address: %s" % exc) from exc
    if r.returncode != 0 or not os.path.exists(binary):
        last = r.stderr.strip().split("\n")[-1:] or [""]
        raise AsanSetupError("clang -fsanitize=address failed: " + last[0][:300])
    return binary


def run(binary, stdin=b"", timeout=300, cwd=None):
    """One run. `kind` is the report's class (heap-buffer-overflow,
    heap-use-after-free, ...) or None when the sanitizer is quiet; the
    program's own exit status is reported either way."""
    env = dict(os.environ, ASAN_OPTIONS=ASAN_OPTIONS)
    try:
        r = subprocess.run([binary], input=stdin, capture_output=True,
                           env=env, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return AsanResult("timeout", "no exit within %ss" % timeout, None, b"", b"")
    err = r.stderr.decode("utf-8", "replace")
    kind = summary = None
    for line in err.split("\n"):
        if "ERROR: AddressSanitizer:" in line:
            head = line.split("ERROR: AddressSanitizer: ", 1)[1]
            kind = head.partition(" on ")[0].strip()
            summary = line.strip()
            break
    return AsanResult(kind, summary, r.returncode, r.stdout, err)


def control():
    """The report kind for a known one-byte over-read. Raises
    AsanSetupError when the instrumented binary cannot be built; any
    answer other than "heap-buffer-overflow" means this toolchain does
    not really detect one."""
    with tempfile.TemporaryDirectory() as td:
        return run(build(CONTROL_IR, td)).kind
