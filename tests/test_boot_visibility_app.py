from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'tests/boot_visibility_app'
ANDROID = '{http://schemas.android.com/apk/res/android}'


class BootVisibilityAppContractTests(unittest.TestCase):
    def test_manifest_is_self_targeted_and_permission_free(self):
        manifest = ET.parse(APP / 'AndroidManifest.xml').getroot()
        package = 'org.kernelstudy.bootvisibilityprobe'
        self.assertEqual(manifest.attrib['package'], package)
        self.assertFalse(manifest.findall('uses-permission'))
        self.assertFalse(manifest.findall('uses-permission-sdk-23'))
        self.assertFalse(manifest.findall('permission'))
        app = manifest.find('application')
        self.assertEqual(app.get(ANDROID + 'debuggable'), 'false')
        self.assertEqual(app.get(ANDROID + 'allowBackup'), 'false')
        self.assertEqual(app.get(ANDROID + 'usesCleartextTraffic'), 'false')
        self.assertEqual(list(app), [])  # no services, receivers, providers or activities
        probe = manifest.find('instrumentation')
        self.assertEqual(probe.get(ANDROID + 'targetPackage'), package)
        self.assertEqual(manifest.find('uses-sdk').get(ANDROID + 'targetSdkVersion'), '37')

    def test_probe_has_explicit_execution_context_guard(self):
        source = (APP / 'src/org/kernelstudy/bootvisibilityprobe/Probe.java').read_text()
        self.assertIn('uid < 10000 || !domain.startsWith("u:r:untrusted_app")', source)
        self.assertIn('new ProcessBuilder("/system/bin/getprop", "ro.boot." + field)', source)
        self.assertNotIn('setprop', source)
        self.assertNotIn('FileOutputStream', source)
        self.assertNotIn('android.security.keystore', source)
        self.assertIn('"not_determined"', source)
        self.assertIn('"not_requested"', source)


if __name__ == '__main__':
    unittest.main()
