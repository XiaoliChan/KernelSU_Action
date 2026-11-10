#!/usr/bin/env python3
"""Exercise the packaged AK3 slot resolver with sandbox partition files.

The real setup_ak implementation is used; boot read/write functions are mocks.
No real device partition is read or written.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def check(archive):
    with zipfile.ZipFile(archive) as z:
        installer = z.read('anykernel.sh').decode()
        core = z.read('tools/ak3-core.sh').decode()
    start = core.index('setup_ak() {')
    end = core.index('\n}', start) + 2
    resolver = core[start:end]
    for slot in ('_a', '_b', ''):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tools').mkdir()
            devices = root / 'dev/block/by-name'
            devices.mkdir(parents=True)
            for name in ('boot_a', 'boot_b'):
                (devices / name).write_text('partition sentinel')
            (root / 'cmdline').write_text('')
            (root / 'mtd').write_text('')
            fixture = resolver.replace('/dev/', f'{root}/dev/')
            fixture = fixture.replace('/proc/cmdline', str(root / 'cmdline'))
            fixture = fixture.replace('/proc/mtd', str(root / 'mtd'))
            prelude = f'''
AKHOME='{root}'; RAMDISK='{root}/ramdisk'; PATCH='{root}/patch';
getprop() {{ [ "$1" = ro.boot.slot_suffix ] && printf '%s' '{slot}'; }}
ui_print() {{ :; }}
abort() {{ echo "ABORT:$*"; exit 42; }}
split_boot() {{ echo "READ:$BLOCK"; }}
flash_boot() {{ echo "WRITE:$BLOCK"; }}
flash_generic() {{ :; }}
'''
            (root / 'tools/ak3-core.sh').write_text(prelude + fixture + '\nsetup_ak;\n')
            (root / 'anykernel.sh').write_text(installer)
            result = subprocess.run(['bash', 'anykernel.sh'], cwd=root,
                                    capture_output=True, text=True)
            if slot:
                assert result.returncode == 0, result.stderr + result.stdout
                expected = f'WRITE:{devices}/boot{slot}'
                assert expected in result.stdout, result.stdout
                other = '_b' if slot == '_a' else '_a'
                assert f'WRITE:{devices}/boot{other}' not in result.stdout
            else:
                assert result.returncode == 42, result.stderr + result.stdout
                assert 'WRITE:' not in result.stdout
            for name in ('boot_a', 'boot_b'):
                assert (devices / name).read_text() == 'partition sentinel'
            print(f'PASS {Path(archive).name}: slot={slot or "missing -> abort"}')


if __name__ == '__main__':
    check(sys.argv[1])
