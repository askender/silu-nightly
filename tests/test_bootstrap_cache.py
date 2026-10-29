"""Installed-wheel bootstrap must treat package sources as read-only."""

import os
import shutil
import subprocess

import pytest

from tools import bootstrap


def test_bootstrap_workspace_is_outside_install_tree(tmp_path, monkeypatch):
    install = tmp_path / "site-packages"
    (install / "silu").mkdir(parents=True)
    (install / "tools").mkdir()
    (install / "selfhost").mkdir()
    for name in bootstrap._TOOLS:
        shutil.copyfile(os.path.join(bootstrap.REPO, "silu", name),
                        install / "silu" / name)
    for name in ("flatten_codegen.py", "flatten_si_tail.si", "siluc_main.c"):
        shutil.copyfile(os.path.join(bootstrap.REPO, "tools", name),
                        install / "tools" / name)
    for name in bootstrap._WRAPPERS + bootstrap._SELFHOST_SOURCES:
        shutil.copyfile(os.path.join(bootstrap.REPO, "selfhost", name),
                        install / "selfhost" / name)
    monkeypatch.setattr(bootstrap, "REPO", str(install))
    original_fingerprint = bootstrap._fingerprint()
    with open(install / "silu" / "typed_codegen.py", "ab") as f:
        f.write(b"\n# cached source changed\n")
    assert bootstrap._fingerprint() != original_fingerprint
    before = {str(p.relative_to(install)): p.read_bytes()
              for p in install.rglob("*") if p.is_file()}
    cache = tmp_path / "cache" / "toolchain"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "flatten_codegen.py" in cmd[1]:
            return subprocess.CompletedProcess(cmd, 0, "# flat test source\n", "")
        if "silu" in cmd[2:4]:
            out = cmd[cmd.index("-o") + 1]
            with open(out, "wb") as f:
                f.write(b"native")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "clang":
            with open(cmd[-1], "wb") as f:
                f.write(b"driver")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    driver, frontend = bootstrap.ensure_toolchain(str(cache))
    assert os.path.dirname(driver) == str(cache)
    assert os.path.isfile(os.path.join(cache, "siluc1"))
    assert os.path.isfile(frontend)
    assert os.path.isfile(cache / "typed_codegen_flat.si")
    assert not (install / "siluc").exists()
    assert not (install / "selfhost" / "typed_codegen_flat.si").exists()
    assert before == {str(p.relative_to(install)): p.read_bytes()
                      for p in install.rglob("*") if p.is_file()}
    count = len(calls)
    assert bootstrap.ensure_toolchain(str(cache)) == (driver, frontend)
    assert len(calls) == count


def test_failed_bootstrap_publishes_no_toolchain(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_generate_flat", lambda path: None)
    monkeypatch.setattr(
        bootstrap.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "build failed"),
    )
    cache = tmp_path / "toolchain"
    with pytest.raises(RuntimeError):
        bootstrap.ensure_toolchain(str(cache))
    assert not cache.exists()


def test_cache_honors_xdg_and_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    first = bootstrap.cache_root()
    assert first.startswith(str(tmp_path))
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "test-arch")
    assert bootstrap.cache_root() != first
