"""Installer policy tests: no device writes and no network access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AnyKernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.ak3 = self.workspace / 'AnyKernel3'
        self.ak3.mkdir()
        self.env = {**os.environ, 'WORKSPACE': str(self.workspace),
                    'KERNEL_DIR': str(self.workspace / 'kernel'),
                    'ANYKERNEL3_DEVICE': 'lemonades', 'ANYKERNEL3_DEVICE_ALIAS': 'OnePlus9R',
                    'ANYKERNEL3_SLOT_DEVICE': '1'}

    def configure(self):
        return subprocess.run(['bash', '-c', '. "$1"; configure_anykernel3',
                               'test', str(ROOT / 'scripts/package.sh')],
                              env=self.env, capture_output=True, text=True)

    def test_example_payloads_removed_and_policy_set(self):
        for folder in ('patch', 'ramdisk', 'modules'):
            (self.ak3 / folder).mkdir()
            (self.ak3 / folder / 'tuna').write_text('example must not ship')
        (self.ak3 / 'anykernel.sh').write_text('is_slot_device=auto;\nappend_file init.tuna.rc')
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        script = (self.ak3 / 'anykernel.sh').read_text()
        self.assertIn('IS_SLOT_DEVICE=1;', script)
        self.assertIn('BLOCK=boot;', script)
        self.assertIn('SLOT_SELECT=active;', script)
        self.assertIn('device.name1=lemonades', script)
        self.assertIn('device.name2=OnePlus9R', script)
        self.assertIn('do.devicecheck=1', script)
        self.assertNotIn('is_slot_device=', script)
        for name in ('init.tuna', 'fstab.tuna', 'dump_boot;', 'write_boot;', 'append_file'):
            self.assertNotIn(name, script)
        for folder in ('patch', 'ramdisk', 'modules'):
            self.assertFalse((self.ak3 / folder).exists())

    def test_only_kernel_and_optional_dtbo_calls(self):
        self.assertEqual(self.configure().returncode, 0)
        tools = self.ak3 / 'tools'
        tools.mkdir()
        (tools / 'ak3-core.sh').write_text('''
[ "$BLOCK" = boot ] && [ "$IS_SLOT_DEVICE" = 1 ] && [ "$SLOT_SELECT" = active ] || exit 1
split_boot() { echo split; }
flash_boot() { echo flash; }
flash_generic() { echo "optional:$1"; }
''')
        result = subprocess.run(['sh', 'anykernel.sh'], cwd=self.ak3,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['split', 'flash', 'optional:dtbo'])

    def test_generic_policy_still_supported(self):
        self.env.update(ANYKERNEL3_DEVICE='', ANYKERNEL3_DEVICE_ALIAS='', ANYKERNEL3_SLOT_DEVICE='auto')
        self.assertEqual(self.configure().returncode, 0)
        script = (self.ak3 / 'anykernel.sh').read_text()
        self.assertIn('IS_SLOT_DEVICE=auto;', script)
        self.assertIn('do.devicecheck=0', script)

    def test_invalid_policy_rejected(self):
        self.env['ANYKERNEL3_DEVICE'] = 'lemonades;exit'
        self.assertNotEqual(self.configure().returncode, 0)
        self.env.update(ANYKERNEL3_DEVICE='lemonades', ANYKERNEL3_SLOT_DEVICE='bogus')
        self.assertNotEqual(self.configure().returncode, 0)

    def test_all_9r_profiles_enforce_device_and_slot(self):
        for path in (ROOT / 'config').glob('oneplus-9r-*.env'):
            config = path.read_text()
            self.assertIn('ANYKERNEL3_DEVICE=lemonades', config)
            self.assertIn('ANYKERNEL3_DEVICE_ALIAS=OnePlus9R', config)
            self.assertIn('ANYKERNEL3_SLOT_DEVICE=1', config)

    def test_alias_needs_primary_device_and_valid_characters(self):
        self.env['ANYKERNEL3_DEVICE'] = ''
        self.assertNotEqual(self.configure().returncode, 0)
        self.env.update(ANYKERNEL3_DEVICE='lemonades', ANYKERNEL3_DEVICE_ALIAS='OnePlus9R;exit')
        self.assertNotEqual(self.configure().returncode, 0)


if __name__ == '__main__':
    unittest.main()
