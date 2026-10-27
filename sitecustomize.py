"""Subprocess coverage hook.

coverage.process_startup() is a no-op unless COVERAGE_PROCESS_START
is set in the environment, which pytest-cov sets for the whole test
run when invoked with --cov. This makes `python -m silu ...` child
processes (spawned by the self-hosting gates, the CLI build commands
and the runtime cache) contribute to the coverage report - without
it, silu/runtime_cache.py, static_gate.py and llvmlite_text.py show
0% because their consumers only ever run in subprocesses.
"""

try:
    import coverage

    coverage.process_startup()
except ImportError:
    pass
