import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boot_visibility', ROOT / 'scripts/audit-boot-visibility.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class BootVisibilityTests(unittest.TestCase):
    def test_allowlist_and_redaction(self):
        report = audit.parse_boot_text('androidboot.serialno=PRIVATE androidboot.verifiedbootstate=orange '
                                       'androidboot.secret=TOKEN androidboot.flash.locked=0')
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertNotIn('TOKEN', json.dumps(report))
        self.assertEqual(report['fields']['verifiedbootstate'][0]['value'], 'orange')
        report = audit.parse_boot_text('androidboot.vbmeta.device_state=PRIVATE')
        self.assertEqual(report['fields']['vbmeta.device_state'][0], {'status': 'unrecognized_value'})
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_duplicates_quotes_and_nul(self):
        report = audit.parse_boot_text('androidboot.verifiedbootstate="green"\x00androidboot.verifiedbootstate=orange')
        self.assertEqual(len(report['fields']['verifiedbootstate']), 2)
        check = audit.consistency({'cmdline': report})
        self.assertEqual(check['conflicting_fields'], ['verifiedbootstate'])
        self.assertTrue(check['mixed_lock_hints'])
        self.assertEqual(audit.parse_boot_text('broken="')['status'], 'parse_error')

    def test_bootconfig_and_missing_values(self):
        report = audit.parse_boot_text('androidboot.vbmeta.device_state = "unlocked"\n'
                                       'androidboot.flash.locked = "0" # comment\n'
                                       'androidboot.serialno = "PRIVATE"', bootconfig=True)
        self.assertEqual(report['fields']['vbmeta.device_state'][0]['value'], 'unlocked')
        self.assertNotIn('PRIVATE', json.dumps(report))
        empty = audit.observation('flash.locked', '')
        self.assertEqual(empty, {'status': 'unset_or_empty'})
        self.assertNotIn('unlocked_looking', audit.consistency({'p': {'fields': {'flash.locked': [empty]}}})['observed_hint_types'])

    def test_local_consistency_never_becomes_attestation_success(self):
        report = audit.parse_boot_text('androidboot.verifiedbootstate=green androidboot.vbmeta.device_state=locked')
        check = audit.consistency({'cmdline': report})
        self.assertFalse(check['mixed_lock_hints'])
        self.assertEqual(check['hardware_lock_state'], 'not_determined')
        self.assertEqual(check['attestation'], 'not_requested')
        red = audit.parse_boot_text('androidboot.verifiedbootstate=red androidboot.secureboot=0')
        self.assertEqual(audit.consistency({'cmdline': red})['observed_hint_types'], [])

    def test_collector_uses_only_read_operations(self):
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[-1] == 'get-state': return subprocess.CompletedProcess(cmd, 0, 'device\n', '')
            if cmd[-2:] == ['id', '-u']: return subprocess.CompletedProcess(cmd, 0, '0\n', '')
            if 'getprop' in cmd: return subprocess.CompletedProcess(cmd, 0, '', '')
            return subprocess.CompletedProcess(cmd, 1, '', 'head: Permission denied')
        report = audit.AdbReader('PRIVATE_SERIAL', run).collect()
        self.assertNotIn('PRIVATE_SERIAL', json.dumps(report))
        self.assertFalse(report['context']['app_sandbox_observed'])
        self.assertEqual(report['sources']['proc_cmdline']['status'], 'permission_denied')
        for cmd in calls:
            operation = cmd[3:]
            self.assertTrue(operation == ['get-state'] or operation[:2] in
                            [['shell', 'id'], ['shell', 'getprop'], ['shell', 'head']])

    def test_absent_device_and_errors_do_not_leak_identifiers(self):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, '', 'device PRIVATE_SERIAL not found')
        with self.assertRaisesRegex(RuntimeError, 'ADB device unavailable'):
            audit.AdbReader('PRIVATE_SERIAL', run).collect()
        self.assertEqual(audit.AdbReader(runner=run).command(['get-state']), ('read_failed', ''))

    def test_private_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            audit.save_private(path, {'schema': 1})
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with self.assertRaises(FileExistsError): audit.save_private(path, {})
