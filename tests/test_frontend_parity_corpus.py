"""Corpus-wide front-end parity: the self-hosted front end (silu_fe)
must produce IR identical (parsed) to the Python front end for every
benchmark, both selfhost programs, and its own source. This is the
gap audit that governs front-end self-hosting: any construct where
the two front ends diverge shows up here first.
"""

import json
import os
import subprocess
import sys

from tests import REPO, ensure_fe_binary


def _corpus():
    files = sorted(
        os.path.join(REPO, "benchmarks", f)
        for f in os.listdir(os.path.join(REPO, "benchmarks"))
        if f.endswith(".si")
    )
    files += [
        os.path.join(REPO, "selfhost", "calc.si"),
        os.path.join(REPO, "selfhost", "ir_interp.si"),
        # the front end parses its own source - the strongest member
        os.path.join(REPO, "selfhost", "silu_fe.si"),
        # and the flattened converter: the largest Silu program there is
        # (the memory regression guard: the copy-into assign matcher
        # once leaked a whole-source copy per lookahead slice here)
        os.path.join(REPO, "selfhost", "typed_codegen_flat.si"),
    ]
    return files


def test_frontend_corpus_parity():
    fe = ensure_fe_binary()
    checked = 0
    for path in _corpus():
        ref = subprocess.run(
            [sys.executable, "-m", "silu", "ir", path, "--format", "json"],
            capture_output=True, text=True, cwd=REPO,
        )
        assert ref.returncode == 0, (path, ref.stderr)
        got = subprocess.run(
            [fe], stdin=open(path), capture_output=True, text=True,
            cwd=os.path.dirname(path),
        )
        assert got.returncode == 0, (path, got.stdout + got.stderr)
        assert json.loads(got.stdout) == json.loads(ref.stdout), (
            f"front ends diverge on {path}"
        )
        checked += 1
    # 25 benchmarks (incl. the Json-sum jsonparse twin + match_int +
    # concat_chain + the P9 char-pair pin + list_ops + pop_clear +
    # dict_ops + record_global + dict_local + str_methods + dict_str)
    # + calc + ir_interp + silu_fe + flat converter
    assert checked == 29
