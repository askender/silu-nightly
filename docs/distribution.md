# Repository and Release Topology

The three GitHub repositories have different roles. They are **not**
three branches of one history and must not be merged into each other.

| Repository | Role | What goes there |
|---|---|---|
| `askender/silu-nightly` (private) | Canonical source and CI | Complete compiler, tests, source tags, build artifacts from CI |
| `askender/silu-lang` (public) | Curated distribution | Bilingual docs, examples, website, public binary Releases |
| `askender/silu` | Paused legacy remote | Nothing new; do not push or delete |

The local checkout's `nightly` remote points at the canonical source
repository. `origin` still points at the paused legacy repository; its
old history is already contained in `nightly`, so there is nothing to
migrate. The public showcase has its own independent local checkout
and unrelated commit history.

## Routine development

```sh
# Source, tests, changelog, and source tags: private canonical repo only
git push nightly main

# Public documentation and examples: use the separate silu-lang checkout
cd ~/aix1/silu-lang
git push origin main
```

Never use `git push origin` from the source checkout while `origin` is
the paused legacy repository. Do not copy the compiler source tree into
the public showcase as part of a documentation or binary release.

## Binary release

1. Finish the version, changelog and docs; push source `main` to
   `silu-nightly` and require its fast CI to pass.
2. Run the self-hosting gates locally and/or dispatch the slow CI layer.
3. Create and push the source tag to `silu-nightly` only:

   ```sh
   git tag v1.16.1
   git push nightly v1.16.1
   ```

4. The tag workflow builds and smoke-tests native archives for macOS
   ARM64/x86_64 and Linux ARM64/x86_64. Artifacts stay in the private
   workflow run until promotion.
5. After all four matrix jobs pass, promote those exact CI artifacts
   using the already-authenticated local GitHub account:

   ```sh
   sh tools/promote_release.sh v1.16.1 <release-run-id>
   ```

   The script downloads the artifacts, checks all four SHA-256 files,
   and creates the public Release in `askender/silu-lang`. It requires
   no cross-repository credential in CI and never publishes source.

The public tag and the private source tag share a version name but live
in independent repositories. Binary archives are Release assets, not
files committed into either Git history.

## Release status and known limitations

- v1.16.1 first batch: macOS Apple Silicon, Linux ARM64 and Linux
  x86_64 binaries are published on the public Releases page and were
  verified end-to-end (extract, cold-cache compile, run hello/fib).
  The Intel-Mac archive was built separately on `macos-15-intel` (the
  release matrix's `macos-13` job sat queued on the shrinking Intel
  pool, and llvmlite >=0.46 has no Intel-Mac wheel so it is pinned to
  0.45.1) and appended to the same release: **all four platform
  archives are now published**.
- The self-hosting converter fixed point (`test_selfhost_fixed_point`)
  passes in CI. `test_pipeline_fixed_point` and the oversized
  single-file case of `test_frontend_parity_corpus` run only on the
  dev machine: the self-hosted front end has a **known memory
  regression** when parsing one very large source file directly
  (~12k-line `typed_codegen_flat.si` needs >15GB and is OOM-killed on
  both the dev machine and standard runners; an October 27 front end
  handled it in ~0.6GB). The normal bootstrap path parses only the
  small import skeleton while the converter expands the large module,
  so self-hosting and ordinary compilation are unaffected. The
  flattened file is excluded from `frontend_parity_corpus` until the
  regression is fixed.
- Follow-up (high priority): bisect `typed_codegen` to find the
  large-file memory regression, then restore the flattened file in
  `frontend_parity_corpus` and the pipeline fixed point in CI.

## Installed-toolchain outputs

`silu bootstrap` treats installed package sources as read-only. Generated
compiler sources and native tools live under
`$XDG_CACHE_HOME/silu-selfhost/` or `~/.cache/silu-selfhost/`, keyed by
source contents and host. The C driver's runtime cache uses
`$XDG_CACHE_HOME/silu-runtime/` or `~/.cache/silu-runtime/`.

Developer-mode fixed-point tests intentionally continue to use the
source checkout's build paths; that is a separate, explicit mode.
