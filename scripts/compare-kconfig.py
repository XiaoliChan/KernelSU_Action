#!/usr/bin/env python3
"""Fail if a diagnostic kernel's effective config differs from its reference."""
import argparse
import json
from pathlib import Path
import re


def values(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        setting = re.fullmatch(r'(CONFIG_[A-Z0-9_]+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_[A-Z0-9_]+) is not set', line)
        if setting:
            result[setting[1]] = setting[2]
        elif disabled:
            result[disabled[1]] = 'n'
    if not result:
        raise ValueError(f'No Kconfig values found: {path}')
    return result


def compare(reference, actual, expected_overrides=None):
    want, got = values(reference), values(actual)
    if expected_overrides is not None:
        if not isinstance(expected_overrides, dict) or any(
                not re.fullmatch(r'CONFIG_[A-Z0-9_]+', key) or not isinstance(value, str)
                for key, value in expected_overrides.items()):
            raise ValueError('Expected overrides must map CONFIG symbols to explicit string values')
        want.update(expected_overrides)
    # Kconfig may omit unavailable disabled symbols. Treat absence as disabled,
    # but do not ignore compiler, version, string, integer or enabled settings.
    return {key: {'reference': want.get(key, 'n'), 'actual': got.get(key, 'n')}
            for key in sorted(want.keys() | got.keys())
            if want.get(key, 'n') != got.get(key, 'n')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference')
    parser.add_argument('actual')
    parser.add_argument('--report', required=True)
    parser.add_argument('--expected-overrides', help='JSON of explicitly expected values; not ignored symbols')
    args = parser.parse_args()
    overrides = json.loads(Path(args.expected_overrides).read_text()) if args.expected_overrides else None
    differences = compare(args.reference, args.actual, overrides)
    Path(args.report).write_text(json.dumps(differences, indent=2) + '\n')
    if differences:
        print(json.dumps(differences, indent=2))
        raise SystemExit('Control configuration drifted; do not compile/publish it as the reference')
    print('PASS: all effective Kconfig values match the working-device reference' +
          (' plus explicit expected overrides' if overrides is not None else ''))
