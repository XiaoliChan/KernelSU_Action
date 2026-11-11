#!/usr/bin/env bash
# Install the pinned native v2 core and the narrowly staged 4.19 port.
# This deliberately never copies the old v1.5.9 susfs_compat backend.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${KERNEL_DIR:?}" "${WORKSPACE:?}"
PORT="$ROOT/patches/oneplus-9r/susfs-v2"
mkdir -p "$WORKSPACE/diagnostics"
python3 - "$ROOT" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
lock = json.loads((root / 'config/reference/oneplus-9r-susfs-v2-lock.json').read_text())
source = root / 'patches/oneplus-9r/susfs-v2/upstream'
for name, expected in lock['files'].items():
    path = source / name.removeprefix('kernel_patches/')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Upstream source checksum mismatch: {name}')
if f'#define SUSFS_VERSION "{lock["version"]}"' not in (source / 'include/linux/susfs.h').read_text():
    raise SystemExit('SUSFS version does not match source lock')
print(f'PASS: native {lock["version"]} core from {lock["commit"]}')
PY
test ! -e "$KERNEL_DIR/fs/susfs_compat.c"
test ! -e "$KERNEL_DIR/fs/susfs.c"
cp "$PORT/upstream/fs/susfs.c" "$KERNEL_DIR/fs/"
cp "$PORT/upstream/include/linux/"*.h "$KERNEL_DIR/include/linux/"
patch -d "$KERNEL_DIR" -p1 --batch --fuzz=0 < "$PORT/001-core-4.19.patch"
patch -d "$KERNEL_DIR" -p1 --batch --fuzz=0 < "$PORT/50_add_susfs_in_kernel-4.19.patch"
patch -d "$KERNEL_DIR/${KSU_DIR:-KernelSU}" -p1 --batch --fuzz=0 < "$PORT/002-ksu-optional-v2-features.patch"
if grep -q 'susfs_mnt_id_backup\|susfs_mnt_id_ida' "$KERNEL_DIR/fs/namespace.c"; then
  echo 'Old SUSFS ID-rewrite/allocator code leaked into the v2 port' >&2
  exit 1
fi
cp "$ROOT/config/reference/oneplus-9r-susfs-v2-lock.json" "$WORKSPACE/diagnostics/susfs-source-lock.json"
sha256sum "$KERNEL_DIR/fs/susfs.c" "$KERNEL_DIR/include/linux/susfs.h" \
  "$KERNEL_DIR/include/linux/susfs_def.h" "$PORT/"*.patch \
  > "$WORKSPACE/diagnostics/susfs-inputs.sha256"
