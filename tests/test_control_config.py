"""The no-root control must fail closed on configuration drift."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kconfig_compare', ROOT / 'scripts/compare-kconfig.py')
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


class ControlConfigTests(unittest.TestCase):
    def test_disabled_missing_and_comments_are_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_text('# generated\nCONFIG_FOO=y\n# CONFIG_BAR is not set\n')
            b.write_text('CONFIG_FOO=y\n')
            self.assertEqual(compare.compare(a, b), {})

    def test_enabled_version_and_string_drift_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_text('CONFIG_RELR=y\nCONFIG_CLANG_VERSION=220002\nCONFIG_LOCALVERSION="-perf"\n')
            b.write_text('CONFIG_RELR=n\nCONFIG_CLANG_VERSION=200000\nCONFIG_LOCALVERSION="-OnePlus9R"\n')
            self.assertEqual(set(compare.compare(a, b)),
                             {'CONFIG_RELR', 'CONFIG_CLANG_VERSION', 'CONFIG_LOCALVERSION'})

    def test_empty_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'empty'
            path.write_text('# only comments\n')
            with self.assertRaises(ValueError):
                compare.values(path)

    def test_control_has_no_release_or_root_installation(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build-oneplus-9r-control.yml').read_text())
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(set(workflow['jobs']), {'control'})
        steps = workflow['jobs']['control']['steps']
        commands = '\n'.join(step.get('run', '') for step in steps)
        self.assertNotIn('scripts/kernelsu.sh', commands)
        self.assertNotIn('scripts/patches.sh', commands)
        self.assertNotIn('action-gh-release', str(steps))
        self.assertIn('scripts/compare-kconfig.py', commands)
        reference = compare.values(ROOT / 'config/reference/oneplus-9r-lineage-24.config')
        self.assertEqual(reference['CONFIG_RELR'], 'y')
        self.assertEqual(reference['CONFIG_LOCALVERSION'], '"-perf"')
        self.assertEqual(reference.get('CONFIG_KSU', 'n'), 'n')


if __name__ == '__main__':
    unittest.main()
