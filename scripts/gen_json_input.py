#!/usr/bin/env python3
"""Generate the shared JSON input for the jsonparse benchmark.

Deterministic bytes for all three implementations (silu / CPython /
Rust); the document is scaffolding, generation is not measured.

    python scripts/gen_json_input.py > /tmp/json_input.txt
    silu llvm-json... etc read it on stdin.
"""

COUNT = 3000


def main() -> None:
    parts = []
    for i in range(COUNT):
        parts.append('{"id":%d,"name":"item%d"}' % (i, i))
    print("[" + ",".join(parts) + "]")


if __name__ == "__main__":
    main()
