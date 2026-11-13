#!/usr/bin/env python3
"""Read-only, allowlisted boot-state observations; never an attestation verdict.

Does not root/reboot the device, write properties, fetch certificates, or save
raw cmdlines, property dumps, identifiers or ADB error output.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

FIELDS = {
    'verifiedbootstate': {'green', 'yellow', 'orange', 'red'},
    'vbmeta.device_state': {'locked', 'unlocked'},
    'flash.locked': {'0', '1'},
    'veritymode': {'enforcing', 'eio', 'logging', 'disabled', 'panicking', 'restart'},
    'secureboot': {'0', '1', 'true', 'false'},
}
PROPERTIES = tuple('ro.boot.' + name for name in FIELDS)
BOOT_KEYS = {'androidboot.' + name: name for name in FIELDS}
SOURCES = {
    'proc_cmdline': '/proc/cmdline',
    'proc_bootconfig': '/proc/bootconfig',
    'dt_bootargs': '/sys/firmware/devicetree/base/chosen/bootargs',
    'proc_dt_bootargs': '/proc/device-tree/chosen/bootargs',
}
LIMIT = 65536


def observation(field, value):
    value = value.strip().lower()
    if not value:
        return {'status': 'unset_or_empty'}
    if value not in FIELDS[field]:
        # Even an allowlisted key can hold arbitrary data. Never echo it.
        return {'status': 'unrecognized_value'}
    return {'status': 'observed', 'value': value}


def parse_boot_text(text, bootconfig=False):
    result = {}
    if bootconfig:
        tokens = []
        for line in text.splitlines():
            m = re.match(r'^\s*(androidboot\.[a-zA-Z0-9_.]+)\s*=\s*(.*?)\s*$', line)
            if m and m[1] in BOOT_KEYS:
                try:
                    values = shlex.split(m[2], comments=True)
                except ValueError:
                    values = ['invalid']
                tokens.append((m[1], values[0] if len(values) == 1 else 'invalid'))
    else:
        try:
            args = shlex.split(text.replace('\x00', ' '), comments=False)
        except ValueError:
            return {'status': 'parse_error', 'fields': {}}
        tokens = [arg.split('=', 1) for arg in args if '=' in arg]
    for key, value in tokens:
        if key in BOOT_KEYS:
            field = BOOT_KEYS[key]
            result.setdefault(field, []).append(observation(field, value))
    return {'status': 'readable', 'fields': result}


def consistency(sources):
    hints, seen = set(), {}
    for source, report in sources.items():
        for field, observations in report.get('fields', {}).items():
            for item in observations:
                if item.get('status') != 'observed':
                    continue
                value = item['value']
                seen.setdefault(field, set()).add(value)
                if ((field == 'verifiedbootstate' and value in {'green', 'yellow'}) or
                    (field == 'vbmeta.device_state' and value == 'locked') or
                    (field == 'flash.locked' and value == '1')):
                    hints.add('locked_looking')
                if ((field == 'verifiedbootstate' and value == 'orange') or
                    (field == 'vbmeta.device_state' and value == 'unlocked') or
                    (field == 'flash.locked' and value == '0')):
                    hints.add('unlocked_looking')
    conflicts = sorted(field for field, values in seen.items() if len(values) > 1)
    return {
        'conflicting_fields': conflicts,
        'mixed_lock_hints': len(hints) > 1,
        'observed_hint_types': sorted(hints),
        'hardware_lock_state': 'not_determined',
        'attestation': 'not_requested',
        'note': 'Local observations are not proof of the bootloader state or Play Integrity status.',
    }


class AdbReader:
    def __init__(self, serial=None, runner=subprocess.run):
        self.prefix = ['adb'] + (['-s', serial] if serial else [])
        self.runner = runner

    def command(self, args):
        try:
            p = self.runner(self.prefix + args, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=10)
        except FileNotFoundError:
            return 'adb_unavailable', ''
        except subprocess.TimeoutExpired:
            return 'timeout', ''
        if p.returncode == 0:
            if len(p.stdout.encode('utf-8')) > LIMIT:
                return 'too_large', ''
            return 'ok', p.stdout
        error = p.stderr.lower()
        if 'permission denied' in error:
            return 'permission_denied', ''
        if 'no such file' in error or 'not found' in error and 'device' not in error:
            return 'unavailable', ''
        return 'read_failed', ''

    def collect(self):
        state, value = self.command(['get-state'])
        if state != 'ok' or value.strip() != 'device':
            raise RuntimeError('ADB device unavailable; reconnect or select --serial. No device changes made.')
        status, uid = self.command(['shell', 'id', '-u'])
        context = {'type': 'adb_shell', 'uid': int(uid.strip()) if status == 'ok' and uid.strip().isdigit() else None,
                   'app_sandbox_observed': False}
        props = {}
        for prop in PROPERTIES:
            field = prop.removeprefix('ro.boot.')
            status, value = self.command(['shell', 'getprop', prop])
            props[field] = [observation(field, value) if status == 'ok' else {'status': status}]
        sources = {'properties': {'status': 'collected', 'fields': props}}
        for name, path in SOURCES.items():
            status, value = self.command(['shell', 'head', '-c', str(LIMIT + 1), path])
            sources[name] = (parse_boot_text(value, bootconfig=name == 'proc_bootconfig')
                             if status == 'ok' else {'status': status, 'fields': {}})
        return {'schema': 1, 'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'context': context, 'sources': sources, 'comparison': consistency(sources)}


def save_private(path, report):
    # Refuse overwrite/symlink targets. Reports must never become public by umask.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o600), 'w') as out:
        json.dump(report, out, indent=2, ensure_ascii=False)
        out.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='ADB serial (not recorded in the report)')
    parser.add_argument('--output', type=Path, help='New report file; mode 0600; refuses overwrite')
    args = parser.parse_args()
    try:
        report = AdbReader(args.serial).collect()
        if args.output:
            save_private(args.output, report)
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
    except (RuntimeError, OSError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
