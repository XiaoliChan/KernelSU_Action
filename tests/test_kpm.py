"""KPM must reject ABI drift, stub payloads, changed config and bundled modules."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kpm', ROOT / 'scripts/kpm-components.py')
kpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kpm)

META = '''[kernel]
patched=true
[kpimg]
version=0xe00
config=android,release
arch=arm64
superkey=<redacted>
root_superkey=<redacted>
[extras]
num=0
'''


class KpmTests(unittest.TestCase):
    def test_protocol_numeric_defines_not_comments(self):
        header = '\n'.join(f'#define {k} {v}UL' for k, v in kpm.PROTOCOL.items())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bridge.h'
            path.write_text(header)
            kpm.check_abi(path)
            path.write_text('/* ABI v2 */\n' + header.replace('ABI_VERSION 2UL', 'ABI_VERSION 1UL'))
            with self.assertRaises(ValueError):
                kpm.check_abi(path)
            path.write_text(header.replace('SUKISU_KPM_SUPERCALL_MAGIC3', 'MISSING'))
            with self.assertRaises(ValueError):
                kpm.check_abi(path)

    def test_real_payload_metadata(self):
        kpm.metadata(META, patched=True)
        for old, new in [('0xe00', '0x0'), ('arm64', 'x86_64'),
                         ('android,release', 'android,debug'),
                         ('patched=true', 'patched=false'), ('num=0', 'num=1'),
                         ('<redacted>', 'plaintext')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                kpm.metadata(META.replace(old, new), patched=True)

    def test_config_without_kpm_is_rejected_before_tool_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'manifest.json').write_text('{}')
            image = d / 'Image'
            raw = b'\x00' * 56 + b'ARMd' + b'\x00' * 4
            image.write_bytes(raw)
            with patch.object(kpm, 'components', return_value={}), \
                 patch.object(kpm, 'embedded_config', return_value=b'CONFIG_KPM=n\n'), \
                 patch.object(kpm, 'listing') as listing:
                with self.assertRaises(ValueError):
                    kpm.patch(d, d / 'bridge.h', image, d / 'reports')
                listing.assert_not_called()
                self.assertEqual(image.read_bytes(), raw)

    def test_changed_components_fail_before_image_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'manifest.json').write_text('{}')
            with patch.object(kpm, 'components', return_value={'changed': True}):
                with self.assertRaises(ValueError):
                    kpm.patch(d, d / 'bridge.h', d / 'nonexistent', d / 'reports')

    def test_kpm_stage_adds_only_kpm_and_never_releases(self):
        adb = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-adbroot-overrides.json').read_text())
        full = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-kpm-overrides.json').read_text())
        self.assertEqual(full, {**adb, 'CONFIG_KPM': 'y'})
        profile = (ROOT / 'config/oneplus-9r-lineage-sukisu-kpm.env').read_text()
        for flag in ('ENABLE_KPM=true', 'ENABLE_SUSFS=false', 'CONFIG_KSU_DEBUG=n',
                     'CONFIG_KSU_FEATURE_ADBROOT=y', 'ENABLE_CCACHE=true'):
            self.assertIn(flag, profile)
        wf = yaml.safe_load((ROOT / '.github/workflows/build-oneplus-9r-sukisu-kpm.yml').read_text())
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        commands = '\n'.join(s.get('run', '') for s in wf['jobs']['kpm']['steps'])
        self.assertIn('scripts/prepare-kpm.sh', commands)
        self.assertIn('CONFIG_KPM=y', commands)
        self.assertIn('cmake zlib1g-dev', commands)
        self.assertNotIn('action-gh-release', str(wf))
        self.assertNotIn('scripts/patches.sh all', commands)


if __name__ == '__main__':
    unittest.main()
