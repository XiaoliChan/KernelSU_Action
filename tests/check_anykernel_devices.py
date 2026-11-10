#!/usr/bin/env python3
"""Run the published AK3 device checker against 9R aliases and wrong models."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import zipfile


def check(archive):
    with zipfile.ZipFile(archive) as z:
        installer = z.read('anykernel.sh').decode()
        backend = z.read('META-INF/com/google/android/update-binary').decode()
    start = backend.index('do_devicecheck() {')
    checker = backend[start:backend.index('\n}', start) + 2]
    keys = ('ro.product.device', 'ro.build.product',
            'ro.product.vendor.device', 'ro.vendor.product.device')
    cases = [('reported-phone', ('OnePlus9R', 'OnePlus9R', 'OnePlus9R', ''), True),
             ('codename', ('lemonades',) * 4, True),
             ('wrong-OnePlus9', ('OnePlus9',) * 4, False),
             ('wrong-lemonade', ('lemonade',) * 4, False),
             ('empty', ('',) * 4, False)]
    for i in range(4):
        props = ['unrelated'] * 4
        props[i] = 'OnePlus9R'
        cases.append((f'alias-property-{i}', tuple(props), True))
    with tempfile.TemporaryDirectory(prefix='device-check-') as tmp:
        root = Path(tmp)
        (root / 'anykernel.sh').write_text(installer)
        getprop = 'getprop() { case "$1" in\n'
        for i, key in enumerate(keys):
            getprop += f'{key}) printf "%s" "$PROP{i}";;\n'
        getprop += 'esac; }\n'
        prelude = '''
file_getprop() { grep "^$2=" "$1" | tail -n1 | cut -d= -f2-; }
ui_print() { :; }
abort() { exit 42; }
'''
        for name, props, accepted in cases:
            env = {**os.environ, **{f'PROP{i}': value for i, value in enumerate(props)}}
            result = subprocess.run(['bash', '-c', prelude + getprop + checker + '\ndo_devicecheck;'],
                                    cwd=root, env=env, capture_output=True, text=True)
            assert result.returncode == (0 if accepted else 42), (name, result.returncode, result.stderr)
            print(f'PASS {Path(archive).name}: {name} -> {"accept" if accepted else "reject"}')


if __name__ == '__main__':
    check(sys.argv[1])
