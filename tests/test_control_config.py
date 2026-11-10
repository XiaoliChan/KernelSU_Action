"""The no-root control must fail closed on configuration drift."""
import importlib.util
import json
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

    def test_compiler_build_number_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_text('CONFIG_CC_VERSION_TEXT="Android (15071444) clang version 22.0.2"\n')
            b.write_text('CONFIG_CC_VERSION_TEXT="Android (15682573) clang version 22.0.2"\n')
            self.assertIn('CONFIG_CC_VERSION_TEXT', compare.compare(a, b))

    def test_explicit_overrides_are_required_values_not_ignore_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'a', Path(tmp) / 'b'
            a.write_text('CONFIG_KPROBES=y\n')
            b.write_text('CONFIG_KPROBES=y\nCONFIG_KSU=y\n')
            self.assertEqual(compare.compare(a, b, {'CONFIG_KSU': 'y'}), {})
            self.assertIn('CONFIG_KSU', compare.compare(a, a, {'CONFIG_KSU': 'y'}))
            b.write_text('CONFIG_KPROBES=n\nCONFIG_KSU=y\nCONFIG_KSU_SUSFS=y\n')
            self.assertEqual(set(compare.compare(a, b, {'CONFIG_KSU': 'y'})),
                             {'CONFIG_KPROBES', 'CONFIG_KSU_SUSFS'})

    def test_minimal_suki_is_diagnostic_and_allows_only_ksu_config_delta(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/build-oneplus-9r-sukisu-minimal.yml').read_text())
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(set(workflow['jobs']), {'minimal'})
        commands = '\n'.join(s.get('run', '') for s in workflow['jobs']['minimal']['steps'])
        self.assertIn('scripts/kernelsu.sh', commands)
        self.assertNotIn('scripts/patches.sh all', commands)
        self.assertNotIn('scripts/patches.sh susfs', commands)
        self.assertIn('CONFIG_KSU_SUSFS=n', commands)
        self.assertIn('CONFIG_KSU_FEATURE_ADBROOT=n', commands)
        self.assertIn('--save-scmversion', commands)
        self.assertNotIn('action-gh-release', str(workflow))
        expected = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-minimal-overrides.json').read_text())
        self.assertEqual(expected, {'CONFIG_KSU': 'y'})
        hooks = (ROOT / 'patches/oneplus-9r/minimal_hooks/kernel-4.19-sukisu.patch').read_text()
        self.assertNotIn('ksu_handle_setresuid', hooks)
        self.assertIn('ksu_handle_vfs_fstat(fd, &stat->size)', hooks)
        self.assertIn('!error && (stat->result_mask & STATX_SIZE)', hooks)

    def test_diagnostic_ccache_paths_identity_and_failure_save(self):
        for workflow_name, profile_name in (
                ('build-oneplus-9r-control.yml', 'oneplus-9r-lineage-control.env'),
                ('build-oneplus-9r-sukisu-minimal.yml', 'oneplus-9r-lineage-sukisu-minimal.env'),
                ('build-oneplus-9r-sukisu-adbroot.yml', 'oneplus-9r-lineage-sukisu-adbroot.env'),
                ('build-oneplus-9r-sukisu-kpm.yml', 'oneplus-9r-lineage-sukisu-kpm.env')):
            workflow = yaml.safe_load((ROOT / '.github/workflows' / workflow_name).read_text())
            job = next(iter(workflow['jobs'].values()))
            self.assertEqual(job['env']['CCACHE_COMPILERCHECK'], 'content')
            self.assertEqual(job['env']['CCACHE_DIR'], '${{ github.workspace }}/kernel_workspace/.ccache')
            restore = next(s for s in job['steps'] if s.get('id') == 'ccache')
            save = next(s for s in job['steps'] if s.get('uses') == 'actions/cache/save@v4')
            self.assertEqual(restore['with']['path'], '${{ env.CCACHE_DIR }}')
            self.assertEqual(save['with']['path'], restore['with']['path'])
            self.assertEqual(save['with']['key'], '${{ steps.ccache.outputs.cache-primary-key }}')
            self.assertIn('github.run_id', restore['with']['key'])
            self.assertIn('github.run_attempt', restore['with']['key'])
            self.assertIn('always()', save['if'])
            self.assertIn("steps.compile.outcome == 'failure'", save['if'])
            self.assertTrue(save['continue-on-error'])
            compile_step = next(s for s in job['steps'] if s.get('id') == 'compile')
            self.assertEqual(compile_step['run'], 'bash scripts/build.sh compile')
            self.assertIn('ENABLE_CCACHE=true', (ROOT / 'config' / profile_name).read_text())

    def test_adbroot_stage_adds_only_adbroot_to_minimal(self):
        minimal = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-minimal-overrides.json').read_text())
        adbroot = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-adbroot-overrides.json').read_text())
        self.assertEqual(adbroot, {**minimal, 'CONFIG_KSU_FEATURE_ADBROOT': 'y'})
        profile = (ROOT / 'config/oneplus-9r-lineage-sukisu-adbroot.env').read_text()
        self.assertIn('ENABLE_SUSFS=false', profile)
        self.assertIn('ENABLE_KPM=false', profile)
        self.assertIn('CONFIG_KSU_DEBUG=n', profile)
        wf = yaml.safe_load((ROOT / '.github/workflows/build-oneplus-9r-sukisu-adbroot.yml').read_text())
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        self.assertNotIn('action-gh-release', str(wf))
        self.assertIn('CONFIG_KSU_FEATURE_ADBROOT=y', str(wf))

    def test_minimal_werror_fixes_keep_strict_build_policy(self):
        hooks = (ROOT / 'patches/oneplus-9r/minimal_hooks/kernel-4.19-sukisu.patch').read_text()
        reboot = hooks.split('diff --git a/kernel/reboot.c b/kernel/reboot.c')[1]
        self.assertLess(reboot.index('int ret = 0;'), reboot.index('+\tksu_handle_sys_reboot('))
        fixes = (ROOT / 'patches/oneplus-9r/ksu_fixes/sukisu-ultra-minimal/002-nonsusfs-werror.patch').read_text()
        self.assertIn('+#ifndef KSU_NO_PREINIT', fixes)
        self.assertEqual(fixes.count('+#ifdef CONFIG_KSU_SUSFS'), 2)
        self.assertIn('+#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)', fixes)
        profile = (ROOT / 'config/oneplus-9r-lineage-sukisu-minimal.env').read_text()
        self.assertIn('DISABLE_CC_WERROR=false', profile)
        self.assertNotIn('-Wno-error', profile)

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
        profile = (ROOT / 'config/oneplus-9r-lineage-control.env').read_text()
        self.assertIn('USE_CUSTOM_CLANG=true', profile)
        self.assertIn('/+archive/9b144befdfd93b90e02c663504fb9f4b95f9faf8/', profile)


if __name__ == '__main__':
    unittest.main()
