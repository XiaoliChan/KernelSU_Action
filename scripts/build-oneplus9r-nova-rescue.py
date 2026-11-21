#!/usr/bin/env python3
"""Reproduce the verified 9R rescue image locally; never talks to a device."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile


BOOT_SIZE = 100663296
BOOT_SHA = "3af7c8d8d3968857381220efff343f1099f5391f0b491cb56036cc8cac44779d"
IMAGE_SHA = "f23676364db04ab7248e7599d57adca33f2c5a908a1937439e474356a785fbed"
PACKER_SHA = "9c07b15a7a0cfee8413b4f1f068227938d30cffb6774dac7b8eba0013c58df70"
RESCUE_SHA = "7ed1851c4bcf93b0df6e21c387a0faedbd45d655dd5a37e5cb634ba9a1f9ff64"
OPTION = b"ksu.force_feature=adb_root:1"
EXEC = b"    exec u:r:ksu:s0 root -- /data/adb/ksud "
RC = (
    b"\non post-fs-data\n    start logd\n" + EXEC + b"post-fs-data\n\n"
    b"on nonencrypted\n" + EXEC + b"services\n\n"
    b"on property:vold.decrypt=trigger_restart_framework\n" + EXEC + b"services\n\n"
    b"on property:sys.boot_completed=1\n" + EXEC + b"boot-completed\n\n\n"
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, error):
    if not condition:
        raise ValueError(error)


def patch_kernel(image):
    require(b"ksu.force_feature\0" in image, "missing Nova boot feature parameter")
    require(not re.search(rb"(?:ksu|kernelsu)\.preinit\x00", image),
            "unexpected separate preinit loader")
    require(image.count(RC + b"\0") == 1 and image.count(EXEC) == 4,
            "unexpected Nova init fragment; refusing an unverified patch")
    return image.replace(RC, RC.replace(b"    exec ", b"    #xec "), 1)


def boot_sections(raw):
    require(len(raw) == BOOT_SIZE and raw[:8] == b"ANDROID!",
            "not the expected 96 MiB Android boot image")

    def u32(offset):
        return struct.unpack_from("<I", raw, offset)[0]

    page = u32(36)
    require(page == 4096 and u32(40) == 2 and u32(24) == u32(1632) == 0,
            "expected boot v2 without second-stage or recovery DTBO sections")
    k, r, dt = u32(8), u32(16), u32(1648)

    def round_up(n):
        return (n + page - 1) // page * page

    rd = page + round_up(k)
    d = rd + round_up(r)
    require(min(k, r, dt) > 0 and d + dt <= len(raw), "invalid section lengths")
    cmdline = (raw[64:576] + raw[608:1632]).partition(b"\0")[0]
    return raw[page:page+k], raw[rd:rd+r], raw[d:d+dt], cmdline


def run_packer(command, work, args):
    result = subprocess.run(command + args, cwd=work, capture_output=True, timeout=180)
    require(result.returncode == 0, f"magiskboot {args[0]} failed ({result.returncode})")


def build(source, packer, runner, output):
    require(not os.path.lexists(output), "output already exists")
    require(sha(packer.read_bytes()) == PACKER_SHA,
            "magiskboot must be the verified tools/magiskboot from run 44863989700")
    opener = gzip.open if source.suffix == ".gz" else open
    with opener(source, "rb") as stream:
        original = stream.read(BOOT_SIZE + 1)
    require(sha(original) == BOOT_SHA, "input is not the verified Nova boot_a backup")
    image, ramdisk, dtb, cmdline = boot_sections(original)
    require(sha(image) == IMAGE_SHA, "unexpected base kernel")
    modified = patch_kernel(image)
    updated_cmdline = cmdline + b" " + OPTION
    require(OPTION.split(b"=")[0] not in cmdline and len(updated_cmdline) < 512,
            "unexpected original command line")

    command = ([str(runner.resolve())] if runner else []) + [str(packer.resolve())]
    with tempfile.TemporaryDirectory(prefix="9r-rescue-") as temp:
        work = Path(temp)
        (work / "original.img").write_bytes(original)
        run_packer(command, work, ["unpack", "-h", "original.img"])
        require((work / "kernel").read_bytes() == image, "unpacked kernel mismatch")
        (work / "kernel").write_bytes(modified)
        header = work / "header"
        text = header.read_bytes()
        rows = [line for line in text.splitlines() if line.startswith(b"cmdline=")]
        require(rows == [b"cmdline=" + cmdline], "unpacked command line mismatch")
        header.write_bytes(text.replace(rows[0], b"cmdline=" + updated_cmdline, 1))
        run_packer(command, work, ["repack", "original.img", "rescue.img"])
        candidate = (work / "rescue.img").read_bytes()

    require(boot_sections(candidate) == (modified, ramdisk, dtb, updated_cmdline),
            "repack did not preserve the checked sections")
    require(original[:64] == candidate[:64] and original[1632:4096] == candidate[1632:4096],
            "unexpected boot header changes")
    require(sha(candidate) == RESCUE_SHA, "output differs from the boot-tested rescue image")
    with output.open("xb") as stream:
        stream.write(candidate)
    return RESCUE_SHA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-boot", required=True, type=Path, help="verified Nova boot backup, raw or .gz")
    parser.add_argument("--magiskboot", required=True, type=Path, help="verified tools/magiskboot from the 9R artifact")
    parser.add_argument("--runner", type=Path, help="optional executable such as qemu-arm-static")
    parser.add_argument("--output", required=True, type=Path, help="new rescue .img file")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        digest = build(args.base_boot, args.magiskboot, args.runner, args.output)
    except (OSError, ValueError, EOFError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"rescue build failed: {exc}\n")
    print(f"{digest}  {args.output}")
    print("Temporary fastboot boot only. Never flash the rescue image.")


if __name__ == "__main__":
    main()
