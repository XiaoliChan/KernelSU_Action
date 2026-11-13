#!/usr/bin/env bash
# Experimental absolute-file core only. Never run for the stable SUSFS profile.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
: "${KERNEL_DIR:?}" "${WORKSPACE:?}"
PORT="$ROOT/patches/oneplus-9r/zeromount"
test "$(git -C "$KERNEL_DIR" rev-parse HEAD)" = 078365e5318de0a30a41f9707070b610bcd20f13
test -f "$KERNEL_DIR/fs/susfs.c"
test ! -e "$KERNEL_DIR/fs/susfs_compat.c"
test ! -e "$KERNEL_DIR/fs/zeromount.c"
python3 - "$ROOT" "$KERNEL_DIR" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
root, kernel = map(Path, sys.argv[1:])
lock = json.loads((root / 'config/reference/oneplus-9r-zeromount-lock.json').read_text())
for name, expected in lock['files'].items():
    data = (root / 'patches/oneplus-9r/zeromount/upstream' / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('ZeroMount provenance mismatch: ' + name)
# Fail closed if the pinned ARM64/SUSFS thread flag allocation changes.
for path in [kernel / 'arch/arm64/include/asm/thread_info.h',
             kernel / 'include/linux/susfs_def.h']:
    if re.search(r'^\s*#define\s+TIF_\w+\s+36\b', path.read_text(), re.M):
        raise SystemExit('ZeroMount recursion bit collision in ' + str(path))
PY
cp "$PORT/fs/zeromount.c" "$KERNEL_DIR/fs/"
cp "$PORT/include/linux/zeromount.h" "$KERNEL_DIR/include/linux/"
patch -d "$KERNEL_DIR" -p1 --batch --fuzz=0 < "$PORT/001-core-hooks-4.19.patch"
mkdir -p "$WORKSPACE/diagnostics"
cp "$ROOT/config/reference/oneplus-9r-zeromount-lock.json" "$WORKSPACE/diagnostics/"
sha256sum "$PORT/001-core-hooks-4.19.patch" "$KERNEL_DIR/fs/zeromount.c" \
  "$KERNEL_DIR/include/linux/zeromount.h" > "$WORKSPACE/diagnostics/zeromount-inputs.sha256"
