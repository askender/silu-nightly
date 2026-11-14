#!/usr/bin/env python3
"""Deploy the playground to silu.askender.xyz (silu-lang Pages).

The wasm workflow's artifacts live in wasm/web/ (index + host_core.mjs
+ five wasm64 modules + BUILD_INFO stamp - no source). This script
copies them into the public silu-lang repo's docs/playground/ and
pushes; GitHub Pages rebuilds (~1 min) and the site updates.

Topology: the Silu sources stay private; only build artifacts ship.

Usage:
    python3 tools/deploy_playground.py [silu-lang-checkout]

The checkout defaults to $SILU_LANG_DIR, then /tmp/silu-lang; it is
cloned (depth 1) when missing and pulled when present.
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "wasm", "web")
ARTIFACTS = [
    "index.html", "host_core.mjs", "siluc1.wasm", "fe.wasm",
    "interp.wasm", "backend.wasm", "wat2wasm.wasm", "BUILD_INFO.txt",
]


def run(cmd, **kw):
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=True, **kw)


def ensure_checkout(path: str) -> str:
    if os.path.isdir(os.path.join(path, ".git")):
        run(["git", "-C", path, "pull", "--ff-only", "origin", "main"])
        return path
    url = "git@github.com:askender/silu-lang.git"
    run(["git", "clone", "--depth", "1", url, path])
    return path


def main() -> int:
    target = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("SILU_LANG_DIR") or "/tmp/silu-lang"
    )
    checkout = ensure_checkout(target)

    # build the artifacts (the example dropdown syncs inside build_web)
    run([sys.executable, os.path.join(REPO, "wasm", "build.py"), "web"])

    dest = os.path.join(checkout, "docs", "playground")
    os.makedirs(dest, exist_ok=True)
    for name in ARTIFACTS:
        src = os.path.join(WEB, name)
        if not os.path.isfile(src):
            sys.exit(f"missing artifact: {src}")
        run(["cp", src, os.path.join(dest, name)])

    run(["git", "-C", checkout, "add", "-A"])
    staged = subprocess.run(
        ["git", "-C", checkout, "diff", "--cached", "--stat"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not staged:
        print("playground already up to date - nothing to push")
        return 0
    run(["git", "-C", checkout, "commit", "-m",
         "playground: refresh artifacts from the nightly build"])
    run(["git", "-C", checkout, "push", "origin", "main"])
    print("pushed - Pages rebuilds in ~1min:",
          "https://silu.askender.xyz/playground/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
