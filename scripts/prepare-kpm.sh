#!/usr/bin/env bash
# Build real, ABI-matched KernelPatch components; never use patch_linux's
# opaque embedded payload (upstream releases have shipped a stub payload).
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${WORKSPACE:?}" "${KERNEL_DIR:?}"
DEST="${WORKSPACE}/kpm-components"
REF=1c5b608916357ac86a94cc736e235db1fac4a29d
ARM_SHA=62d66e0ad7bd7f2a183d236ee301a5c73c737c886c7944aa4f39415aab528daf
ARM_URL=https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu/12.2.rel1/binrel/arm-gnu-toolchain-12.2.rel1-x86_64-aarch64-none-elf.tar.xz
test "$(uname -m)" = x86_64
mkdir -p "$DEST" "$WORKSPACE/diagnostics"
# Fresh checkout prevents cached objects from silently belonging to another ABI.
SRC=$(mktemp -d "$DEST/source.XXXXXX")
trap 'rm -rf "$SRC"' EXIT
git -C "$SRC" init -q
git -C "$SRC" remote add origin https://github.com/SukiSU-Ultra/SukiSU_KernelPatch_patch.git
git -C "$SRC" -c http.version=HTTP/1.1 fetch -q --depth=1 origin "$REF"
git -C "$SRC" checkout -q --detach FETCH_HEAD
test "$(git -C "$SRC" rev-parse HEAD)" = "$REF"
python3 "$ROOT/scripts/kpm-components.py" abi \
  "$KERNEL_DIR/${KSU_DIR:-KernelSU}/kernel/extension/kpm/bridge.h" \
  "$SRC/kernel/patch/sukisu/supercall.h"
curl --fail --location --retry 3 "$ARM_URL" -o "$DEST/arm-toolchain.tar.xz"
echo "$ARM_SHA  $DEST/arm-toolchain.tar.xz" | sha256sum -c -
mkdir -p "$SRC/compiler"
tar -xJf "$DEST/arm-toolchain.tar.xz" -C "$SRC/compiler" --strip-components=1
PREFIX="$SRC/compiler/bin/aarch64-none-elf-"
"${PREFIX}gcc" --version > "$WORKSPACE/diagnostics/kpm-compiler.txt"
make -C "$SRC/kernel" -j"$(nproc)" TARGET_COMPILE="$PREFIX" kpimg
cmake -S "$SRC/tools" -B "$SRC/host-build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$SRC/host-build" -j"$(nproc)"
cp "$SRC/kernel/kpimg" "$DEST/kpimg"
cp "$SRC/host-build/kptools" "$DEST/kptools"
cp "$SRC/kernel/patch/sukisu/supercall.h" "$DEST/supercall.h"
printf '%s\n' "$REF" > "$DEST/source-commit.txt"
printf '%s\n' "$ARM_SHA" > "$DEST/compiler-archive.sha256"
python3 "$ROOT/scripts/kpm-components.py" components "$DEST" \
  "$KERNEL_DIR/${KSU_DIR:-KernelSU}/kernel/extension/kpm/bridge.h"
cp "$DEST/manifest.json" "$WORKSPACE/diagnostics/kpm-components.json"
