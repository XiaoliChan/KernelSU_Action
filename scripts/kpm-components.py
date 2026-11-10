#!/usr/bin/env python3
"""Fail-closed KPM ABI/payload checks and atomic arm64 Image patching."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import zlib

SOURCE_REF = '1c5b608916357ac86a94cc736e235db1fac4a29d'
ARM_SHA = '62d66e0ad7bd7f2a183d236ee301a5c73c737c886c7944aa4f39415aab528daf'
PROTOCOL = {
    'SUKISU_KPM_SUPERCALL_MAGIC': 0x53554b504d000002,
    'SUKISU_KPM_SUPERCALL_MAGIC2': 0x4b504d4252494447,
    'SUKISU_KPM_SUPERCALL_MAGIC3': 0x53554b494e544552,
    'SUKISU_KPM_ABI_VERSION': 2,
    'SUKISU_KPM_PROBE': 0,
    'SUKISU_KPM_OUTPUT_MAX': 4096,
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_abi(*headers):
    for header in headers:
        definitions = dict(re.findall(
            r'^\s*#define\s+(SUKISU_KPM_\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)[uUlL]*\s*$',
            Path(header).read_text(), re.M))
        actual = {key: int(definitions.get(key, '-1'), 0) for key in PROTOCOL}
        if actual != PROTOCOL:
            raise ValueError(f'Incompatible KPM bridge: {header}: {actual}')


def metadata(text, patched=False):
    cfg = configparser.ConfigParser(interpolation=None, strict=True)
    cfg.read_string(text)
    if (cfg['kpimg']['version'] != '0xe00' or
            cfg['kpimg']['arch'] != 'arm64' or
            set(cfg['kpimg']['config'].split(',')) != {'android', 'release'}):
        raise ValueError('Invalid/stub KPM payload metadata')
    for key in ('superkey', 'root_superkey'):
        if cfg['kpimg'].get(key) != '<redacted>':
            raise ValueError('KPM metadata must redact secrets')
    if patched and (cfg['kernel']['patched'] != 'true' or cfg['extras']['num'] != '0'):
        raise ValueError('KPM patch missing, or unexpected bundled modules')
    return cfg


def listing(tool, *args):
    return subprocess.check_output([str(tool), '-l', *map(str, args)], text=True)


def components(directory, bridge):
    directory = Path(directory)
    check_abi(bridge, directory / 'supercall.h')
    if (directory / 'source-commit.txt').read_text().strip() != SOURCE_REF:
        raise ValueError('Unexpected KernelPatch source revision')
    if (directory / 'compiler-archive.sha256').read_text().strip() != ARM_SHA:
        raise ValueError('Unexpected payload compiler archive')
    if (directory / 'kpimg').stat().st_size < 4096:
        raise ValueError('Stub/truncated kpimg')
    metadata(listing(directory / 'kptools', '-k', directory / 'kpimg'))
    return {'source_commit': SOURCE_REF, 'compiler_archive_sha256': ARM_SHA,
            'protocol': PROTOCOL, 'files': {name: sha(directory / name)
            for name in ('kpimg', 'kptools', 'supercall.h')}}


def embedded_config(data):
    start = data.index(b'IKCFG_ST') + 8
    end = data.index(b'IKCFG_ED', start)
    return zlib.decompress(data[start:end], 16 + zlib.MAX_WBITS)


def patch(directory, bridge, image, report):
    directory, image, report = map(Path, (directory, image, report))
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, expected in manifest.get('files', {}).items():
        if name not in ('kpimg', 'kptools', 'supercall.h') or sha(directory / name) != expected:
            raise ValueError('KPM component digest mismatch before tool execution')
    if components(directory, bridge) != manifest:
        raise ValueError('KPM components changed after preparation')
    original = image.read_bytes()
    if original[56:60] != b'ARMd':
        raise ValueError('Expected uncompressed arm64 Image')
    config = embedded_config(original)
    if b'CONFIG_KPM=y' not in config.splitlines():
        raise ValueError('Refusing to patch a kernel without CONFIG_KPM=y')
    tool = directory / 'kptools'
    before = configparser.ConfigParser(interpolation=None)
    before.read_string(listing(tool, '-i', image))
    if before['kernel']['patched'] != 'false':
        raise ValueError('Refusing to double-patch Image')
    report.mkdir(parents=True, exist_ok=True)
    # Private random key goes only through stdin, never argv/logs/manifest.
    # SukiSU uses the EL1 bridge, not this legacy key interface.
    with tempfile.TemporaryDirectory(prefix='.kpm-', dir=image.parent) as tmp:
        output = Path(tmp) / 'Image'
        result = subprocess.run([str(tool), '--patch', '--image', str(image),
                                 '--kpimg', str(directory / 'kpimg'), '--skey-fd', '0',
                                 '--out', str(output)], input=secrets.token_hex(24),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (report / 'kpm-patch.log').write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(f'kptools failed ({result.returncode}); see kpm-patch.log')
        info = listing(tool, '-i', output)
        metadata(info, patched=True)
        if output.stat().st_size <= len(original) or embedded_config(output.read_bytes()) != config:
            raise ValueError('Patched Image size/config validation failed')
        (report / 'kpm-image.txt').write_text(info)
        manifest.update(input_image_sha256=hashlib.sha256(original).hexdigest(),
                        output_image_sha256=sha(output), bundled_modules=0)
        (report / 'kpm-patch.json').write_text(json.dumps(manifest, indent=2) + '\n')
        output.chmod(image.stat().st_mode & 0o777)
        output.replace(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    abi = sub.add_parser('abi')
    abi.add_argument('headers', type=Path, nargs='+')
    comp = sub.add_parser('components')
    comp.add_argument('directory', type=Path)
    comp.add_argument('bridge', type=Path)
    pat = sub.add_parser('patch')
    for name in ('directory', 'bridge', 'image', 'report'):
        pat.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == 'abi':
        check_abi(*args.headers)
    elif args.command == 'components':
        result = components(args.directory, args.bridge)
        (args.directory / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    else:
        patch(args.directory, args.bridge, args.image, args.report)
    print(f'PASS: KPM {args.command}')


if __name__ == '__main__':
    main()
