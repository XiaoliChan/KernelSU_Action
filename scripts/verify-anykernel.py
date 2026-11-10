#!/usr/bin/env python3
"""Audit a default kernel-only AnyKernel3 archive before upload/release."""
import argparse
import hashlib
from pathlib import Path
import stat
import zipfile


def verify(archive, device, slot, image_name, image):
    template = (Path(__file__).resolve().parents[1] / 'packaging/anykernel.sh').read_text()
    expected = template.replace('IS_SLOT_DEVICE=auto;', f'IS_SLOT_DEVICE={slot};')
    if device:
        expected = expected.replace('do.devicecheck=0', 'do.devicecheck=1')
        expected = expected.replace('device.name1=\n', f'device.name1={device}\n')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP CRC check failed')
        if z.read('anykernel.sh').decode() != expected:
            raise ValueError('installer differs from the audited kernel-only policy')
        if any(n.startswith(('patch/', 'ramdisk/', 'modules/', '.git/')) for n in z.namelist()):
            raise ValueError('unexpected ramdisk/module/example payload')
        for name in ('META-INF/com/google/android/update-binary', 'tools/busybox', 'tools/magiskboot'):
            if not z.read(name):
                raise ValueError(f'empty executable: {name}')
            if not (z.getinfo(name).external_attr >> 16) & stat.S_IXUSR:
                raise ValueError(f'missing executable mode: {name}')
        core = z.read('tools/ak3-core.sh').decode()
        if 'case $IS_SLOT_DEVICE in' not in core:
            raise ValueError('unexpected AK3 slot-detection interface')
        digest = hashlib.sha256(z.read(image_name)).hexdigest()
        if digest != hashlib.sha256(Path(image).read_bytes()).hexdigest():
            raise ValueError('packaged kernel differs from the build output')
    print(f'PASS {Path(archive).name}: device={device or "generic"}, slot={slot}, Image SHA256={digest}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--device', default='')
    parser.add_argument('--slot', choices=['auto', '0', '1'], default='auto')
    parser.add_argument('--image-name', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    verify(args.archive, args.device, args.slot, args.image_name, args.image)
