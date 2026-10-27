"""Shared test configuration.

Subprocess coverage wiring. pytest-cov 7.x does NOT export
COVERAGE_PROCESS_START, so child `python -m silu` processes (spawned
by the gates, CLI build commands and the runtime cache) contribute
nothing to the report - silu/runtime_cache.py, static_gate.py and
llvmlite_text.py all showed 0% purely for that reason.

When --cov is active this conftest sets the variable itself,
pointing at pyproject.toml (whose [tool.coverage.run] carries
source/parallel), and puts the repo root on PYTHONPATH so the
repo-root sitecustomize.py (which calls coverage.process_startup())
is importable at child startup - a `-m` child's cwd injection into
sys.path happens after site processing, too late for
sitecustomize. With no --cov, nothing here changes any environment.
"""

import os


def pytest_configure(config):
    cov_on = bool(
        getattr(config.option, "cov", None)
        or getattr(config.option, "cov_source", None)
    )
    if not cov_on:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["COVERAGE_PROCESS_START"] = os.path.join(root, "pyproject.toml")
    existing = os.environ.get("PYTHONPATH", "")
    if root not in existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = root + os.pathsep + existing
