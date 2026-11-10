"""Offline tests of the real packaging script and workflow release commands."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/build-kernel.yml').read_text())
STEPS = WORKFLOW['jobs']['release']['steps']
PREPARE = next(s['run'] for s in STEPS if s['name'] == 'Prepare release assets and checksums')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.artifacts = self.work / 'artifacts'
        self.ak3 = self.artifacts / 'AnyKernel3-test'
        self.ak3.mkdir(parents=True)
        self.image = self.artifacts / 'Image-test' / 'Image'
        self.image.parent.mkdir()
        self.image.write_bytes(b'kernel fixture')
        self.archive = self.ak3 / 'AnyKernel3-test.zip'
        with zipfile.ZipFile(self.archive, 'w') as z:
            z.writestr('Image', b'kernel fixture')

    def prepare(self):
        return subprocess.run(['bash', '-c', PREPARE], cwd=self.work,
                              env={**os.environ, 'KERNEL_IMAGE_NAME': 'Image'},
                              capture_output=True, text=True)

    def test_required_and_optional_assets(self):
        for name in ('boot.img', 'dtbo.img'):
            d = self.artifacts / name
            d.mkdir()
            (d / name).write_bytes(b'optional fixture')
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        release = self.work / 'release'
        self.assertEqual(len(list(release.iterdir())), 4)
        self.assertFalse((release / 'Image').exists())
        subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=release, check=True,
                       capture_output=True)
        self.assertEqual(self.archive.read_bytes(), (release / self.archive.name).read_bytes())

    def test_no_optional_assets(self):
        self.assertEqual(self.prepare().returncode, 0)
        self.assertEqual({p.name for p in (self.work / 'release').iterdir()},
                         {self.archive.name, 'SHA256SUMS'})
        self.assertNotIn('  Image\n', (self.work / 'release/SHA256SUMS').read_text())
        with zipfile.ZipFile(self.work / 'release' / self.archive.name) as z:
            self.assertEqual(z.read('Image'), b'kernel fixture')

    def test_compressed_raw_image_not_released(self):
        self.image.rename(self.image.with_name('Image.gz-dtb'))
        result = subprocess.run(['bash', '-c', PREPARE], cwd=self.work,
                                env={**os.environ, 'KERNEL_IMAGE_NAME': 'Image.gz-dtb'},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertFalse((self.work / 'release/Image.gz-dtb').exists())

    def test_missing_zip_fails(self):
        self.archive.unlink()
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_corrupt_zip_fails(self):
        self.archive.write_bytes(b'broken zip')
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_missing_image_fails(self):
        self.image.unlink()
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_empty_image_fails(self):
        self.image.write_bytes(b'')
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_ambiguous_image_fails(self):
        extra = self.artifacts / 'Image-extra'
        extra.mkdir()
        (extra / 'Image').write_bytes(b'another kernel')
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_multiple_archives_fail(self):
        shutil.copy(self.archive, self.ak3 / 'extra.zip')
        self.assertNotEqual(self.prepare().returncode, 0)

    def test_packager_preserves_modes_and_symlinks(self):
        source = self.work / 'ak3.git'
        entry = source / 'META-INF/com/google/android/update-binary'
        entry.parent.mkdir(parents=True)
        entry.write_text('#!/sbin/sh\n')
        entry.chmod(0o755)
        (source / 'anykernel.sh').write_text('# fixture\n')
        (source / 'entry-link').symlink_to('META-INF/com/google/android/update-binary')
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        workspace = self.work / 'workspace'
        boot = workspace / 'kernel/out/arch/arm64/boot'
        boot.mkdir(parents=True)
        (boot / 'Image').write_bytes(b'kernel fixture')
        result = subprocess.run(['bash', str(ROOT / 'scripts/package.sh'), 'anykernel3'],
                                env={**os.environ, 'WORKSPACE': str(workspace),
                                     'KERNEL_DIR': str(workspace / 'kernel'), 'ARCH': 'arm64',
                                     'KERNEL_IMAGE_NAME': 'Image', 'USE_CUSTOM_ANYKERNEL3': 'true',
                                     'CUSTOM_ANYKERNEL3_SOURCE': str(source),
                                     'DEVICE': 'OnePlus9R', 'BUILD_TIME': 'test'},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        archive = next(workspace.glob('AnyKernel3*.zip'))
        with zipfile.ZipFile(archive) as z:
            mode = z.getinfo('META-INF/com/google/android/update-binary').external_attr >> 16
            self.assertTrue(mode & stat.S_IXUSR)
            self.assertTrue(stat.S_ISLNK(z.getinfo('entry-link').external_attr >> 16))
            self.assertIn('Image', z.namelist())
            self.assertNotIn('.git/config', z.namelist())

    def test_workflow_contract(self):
        self.assertFalse((ROOT / '.github/workflows/build-oneplus-9r.yml').exists())
        self.assertFalse((ROOT / '.github/workflows/build-oneplus-9r-kernelsu.yml').exists())
        self.assertFalse((ROOT / 'config/oneplus-9r-lineage-kernelsu.env').exists())
        for suffix in ('bakasu', 'sukisu'):
            path = ROOT / f'.github/workflows/build-oneplus-9r-{suffix}.yml'
            # BaseLoader avoids YAML 1.1 interpreting GitHub's "on" as True.
            wf = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            self.assertEqual(wf['on']['workflow_dispatch']['inputs']['publish_release']['default'], 'true')
            self.assertEqual(wf['jobs']['build']['with']['publish_release'], '${{ inputs.publish_release }}')
        meta = next(s['run'] for s in WORKFLOW['jobs']['build']['steps']
                    if s.get('id') == 'meta')
        tags = set()
        for variant in ('kernelsu', 'bakasu', 'sukisu-ultra'):
            for attempt in ('1', '2'):
                output = self.work / f'{variant}-{attempt}.out'
                env = {**os.environ, 'DEVICE': 'OnePlus9R', 'BUILD_TIME': '202611101000',
                       'KSU_VARIANT': variant, 'KERNEL_IMAGE_NAME': 'Image',
                       'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': attempt,
                       'GITHUB_OUTPUT': str(output)}
                subprocess.run(['bash', '-eu', '-c', meta], env=env, check=True)
                tags.add(next(x for x in output.read_text().splitlines() if x.startswith('release_tag=')))
        self.assertEqual(len(tags), 6)
        release = WORKFLOW['jobs']['release']
        self.assertIn("needs.build.result == 'success'", release['if'])
        create = next(s['with'] for s in STEPS if s['name'] == 'Create release')
        self.assertEqual(create['target_commitish'], '${{ github.sha }}')


if __name__ == '__main__':
    unittest.main()
