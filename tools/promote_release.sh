#!/bin/sh
# Promote CI-built binaries, never an untested local compiler build.
# Usage: tools/promote_release.sh v1.16.1 <release-run-id>
set -eu
TAG=${1:?tag required}
RUN_ID=${2:?successful release run id required}
DEST=$(mktemp -d)
trap 'rm -rf "$DEST"' EXIT

actual=$(gh run view "$RUN_ID" --repo askender/silu-nightly \
    --json name,status,conclusion,headBranch \
    --jq '[.name,.status,.conclusion,.headBranch]|join(" ")')
[ "$actual" = "release completed success $TAG" ] || {
    echo "not a successful release run for $TAG: $actual"
    exit 1
}

gh run download "$RUN_ID" --repo askender/silu-nightly --dir "$DEST"
set -- "$DEST"/*/*.tar.gz "$DEST"/*/*.tar.gz.sha256
[ "$#" -eq 8 ] || { echo "expected four archives and four checksums"; exit 1; }
for checksum in "$DEST"/*/*.tar.gz.sha256; do
    archive=${checksum%.sha256}
    expected=$(cut -d' ' -f1 < "$checksum")
    actual=$(shasum -a 256 "$archive" | cut -d' ' -f1)
    [ "$expected" = "$actual" ] || { echo "checksum failed: $archive"; exit 1; }
done

gh release create "$TAG" "$@" --repo askender/silu-lang \
    --title "Silu $TAG" \
    --notes "Self-hosted native compiler for macOS and Linux. Keep siluc and siluc1 together; clang is required. Language subset, semantics and prover scope: https://silu.askender.xyz/"
