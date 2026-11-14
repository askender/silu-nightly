"""Sync the playground's example dropdown with the gate corpus.

Reads wasm/examples/*.si (the curated gate examples - every one joins
the run/backend/wat2wasm gates automatically) and rewrites the EXAMPLES
+ EXAMPLE_TEXT blocks in wasm/web/index.html INLINE: the deployed
playground dir is self-contained (no repo-root fetch paths), and a new
gate example becomes a playground entry with zero manual steps.

Backtick / `${` / backslash would break the JS template literals - the
checker refuses such a file rather than emitting broken JS (the corpus
is plain ASCII Silu, so this has never fired).
"""

import os
import re

# the curated two open the list, then every gate example follows in
# alphabetical order - a new example dropped into wasm/examples/ joins
# the playground with no edits here (the directory IS the source of
# truth, matching how the gates enumerate it)
HEAD = ["recursion.si", "loops.si"]
BASE = "wasm/examples"
CO_BASE = "wasm/examples_compile_only"


def _order() -> list:
    names = sorted(
        f for f in os.listdir(BASE)
        if f.endswith(".si") and f not in HEAD
    )
    return HEAD + names


COMPILE_ONLY = ["containers.si"]


def _read_checked(path: str) -> str:
    txt = open(path, encoding="utf-8").read().rstrip("\n")
    for hazard in ("`", "${", "\\"):
        if hazard in txt:
            raise ValueError(
                f"{path} contains {hazard!r} - would break the JS "
                "template literal; adjust the example or the emitter"
            )
    return txt


def sync(index_path: str) -> int:
    entries = [(f, _read_checked(os.path.join(BASE, f))) for f in _order()]
    for f in COMPILE_ONLY:
        entries.append((f + " (compile-only)",
                        _read_checked(os.path.join(CO_BASE, f))))

    disp = []
    for name, _ in entries:
        path = name if name.endswith("(compile-only)") else f"{BASE}/{name}"
        disp.append(f'  "{name}": "{path}",')
    examples_block = "const EXAMPLES = {\n" + "\n".join(disp) + "\n};"

    texts = [f'  "{name}": `{txt}`,' for name, txt in entries]
    text_block = "const EXAMPLE_TEXT = {\n" + "\n".join(texts) + "\n};"

    html = open(index_path, encoding="utf-8").read()
    m = re.search(r"const EXAMPLES = \{.*?\n\};", html, re.S)
    if not m:
        raise ValueError("EXAMPLES block not found in " + index_path)
    html = html[:m.start()] + examples_block + html[m.end():]
    m = re.search(r"const EXAMPLE_TEXT = \{.*?\n\};", html, re.S)
    if not m:
        raise ValueError("EXAMPLE_TEXT block not found in " + index_path)
    html = html[:m.start()] + text_block + html[m.end():]
    open(index_path, "w", encoding="utf-8").write(html)
    return len(entries)


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    n = sync(os.path.join(repo, "wasm", "web", "index.html"))
    print(f"playground examples synced: {n} entries")
