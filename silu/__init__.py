"""Silu: a small Python-subset language that compiles through LLVM.

The package version tracks the repository's git tags (see CHANGELOG.md).
Importers stay lazy: this module must not pull in submodules at import
time (the CLI lazy-import work, v1.5.1).
"""

__version__ = "1.21.0"
