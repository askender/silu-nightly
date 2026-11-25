#!/bin/sh
# One command = every gate, in CI order, with a single verdict line.
#
#   tools/gates.sh            ruff + IR planes + .ll planes + full pytest
#   tools/gates.sh --no-pytest  the planes only (seconds..minutes)
#
# "All gates green" means this script exited 0 AND the CI run for the
# pushed HEAD is green (it prints that run's conclusion at the end).
# The harness refreshes its own plane binaries; nothing here can pass on
# a stale siluc1 / silu_fe.
#
# Environment: PY selects the interpreter (must have llvmlite - the bare
# homebrew python3 hides the build/llvm subcommands and turns every gate
# red with "invalid choice").
set -u

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO" || exit 2

DEFAULT_PY=/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3
if [ -n "${PY:-}" ]; then
    :
elif [ -x "$DEFAULT_PY" ]; then
    PY=$DEFAULT_PY
else
    PY=python3
fi

RUN_PYTEST=1
for arg in "$@"; do
    case "$arg" in
        --no-pytest) RUN_PYTEST=0 ;;
        *) echo "usage: tools/gates.sh [--no-pytest]" >&2; exit 2 ;;
    esac
done

if ! "$PY" -c "import llvmlite" 2>/dev/null; then
    echo "FAIL python: $PY has no llvmlite" >&2
    exit 1
fi

fail=0
step() {
    name=$1
    shift
    printf '%-34s' "$name"
    if out=$("$@" 2>&1); then
        echo "PASS  $(printf '%s' "$out" | tail -1)"
    else
        echo "FAIL"
        printf '%s\n' "$out" | tail -25
        fail=1
    fi
}

step "ruff (silu/ tools/)"      "$PY" -m ruff check silu/ tools/
step "ir  fe vs rustfe"         "$PY" reference/diff_harness.py ir fe rustfe
step "ir  fe vs pyir"           "$PY" reference/diff_harness.py ir fe pyir
step "ll  conv vs rustconv"     "$PY" reference/diff_harness.py ll conv rustconv
step "ll  conv vs pyll"         "$PY" reference/diff_harness.py ll conv pyll
if [ "$RUN_PYTEST" = 1 ]; then
    step "pytest (full)"        "$PY" -m pytest tests/ -q -p no:cacheprovider
fi

# the verdict of the run GitHub actually executed for this commit, when
# the commit is pushed and gh is available - a red run here means the
# gates are not green whatever the local result says
if command -v gh >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
    head_sha=$(git rev-parse HEAD 2>/dev/null)
    if [ -n "$head_sha" ] && git merge-base --is-ancestor "$head_sha" nightly/main 2>/dev/null; then
        ci=$(gh run list -R askender/silu-nightly --commit "$head_sha" --json conclusion,name \
             --jq '[.[] | select(.name == "ci") | (.conclusion // "in_progress")] | first // "unknown"' 2>/dev/null)
        case "$ci" in
            success)                echo "ci   (GitHub, HEAD)            PASS" ;;
            in_progress|unknown|'') echo "ci   (GitHub, HEAD)            pending / unreachable" ;;
            *)                      echo "ci   (GitHub, HEAD)            FAIL ($ci)"; fail=1 ;;
        esac
    else
        echo "ci   (GitHub, HEAD)            not pushed yet"
    fi
fi

if [ "$fail" = 0 ]; then
    echo "=== ALL GATES GREEN ==="
else
    echo "=== GATES FAILED ==="
fi
exit "$fail"
