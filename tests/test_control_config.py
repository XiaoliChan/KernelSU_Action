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
                ('build-oneplus-9r-sukisu-kpm.yml', 'oneplus-9r-lineage-sukisu-kpm.env'),
                ('build-oneplus-9r-sukisu-susfs.yml', 'oneplus-9r-lineage-sukisu-susfs.env')):
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
            self.assertIn('bash scripts/build.sh compile', compile_step['run'])
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

    def test_susfs_v2_stage_keeps_combined_root_and_isolates_mount_lifecycle(self):
        kpm = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-kpm-overrides.json').read_text())
        expected = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-susfs-overrides.json').read_text())
        self.assertTrue(all(expected[k] == v for k, v in kpm.items()))
        self.assertTrue(all(k.startswith('CONFIG_KSU_SUSFS') for k in expected.keys() - kpm.keys()))
        self.assertNotIn('CONFIG_KSU_SUSFS_SUS_MAP', expected)
        wf = yaml.safe_load((ROOT / '.github/workflows/build-oneplus-9r-sukisu-susfs.yml').read_text())
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        commands = '\n'.join(s.get('run', '') for s in wf['jobs']['susfs']['steps'])
        for flag in ('CONFIG_KSU_SUSFS_SUS_MAP=n', 'CONFIG_KSU_FEATURE_ADBROOT=y', 'CONFIG_KPM=y', '--fuzz=0'):
            self.assertIn(flag, commands)
        self.assertNotIn('action-gh-release', str(wf))
        self.assertNotIn('scripts/patches.sh all', commands)
        self.assertIn('scripts/prepare-susfs-v2.sh', commands)
        self.assertNotIn('50_add_susfs_in_kernel-4.19.patch', commands)
        self.assertNotIn('cp patches/oneplus-9r/fs/', commands)
        for flag in ('SUS_PATH', 'SUS_KSTAT', 'OPEN_REDIRECT', 'HIDE_KSU_SUSFS_SYMBOLS'):
            self.assertIn('CONFIG_KSU_SUSFS_' + flag + '=n', commands)
        minimal = (ROOT / 'patches/oneplus-9r/minimal_hooks/kernel-4.19-sukisu.patch').read_text()
        extra = (ROOT / 'patches/oneplus-9r/susfs_hooks/kernel-4.19-uid.patch').read_text()
        legacy = (ROOT / 'patches/oneplus-9r/kernel_hooks/kernel-4.19-sukisu-ultra.patch').read_text()
        self.assertEqual(legacy, minimal + extra)
        self.assertEqual(extra.count('ksu_handle_setresuid(target_uid,'), 1)
        self.assertIn('target_uid = new->uid.val', extra)
        self.assertLess(extra.index('if (retval < 0)'), extra.index('ksu_handle_setresuid(target_uid,'))
        self.assertLess(extra.index('ksu_handle_setresuid(target_uid,'), extra.index('return commit_creds(new)'))
        sid_fix = (ROOT / 'patches/oneplus-9r/ksu_fixes/sukisu-ultra/002-susfs-old-kernel-sids.patch').read_text()
        self.assertIn('out_flush:', sid_fix)
        self.assertIn('reset_avc_cache();', sid_fix)
        self.assertIn('+#ifdef CONFIG_KSU_SUSFS', sid_fix)
        self.assertIn('+    susfs_set_batch_sid();', sid_fix)
        self.assertLess(sid_fix.index('reset_avc_cache();'), sid_fix.index('+    susfs_set_batch_sid();'))
        self.assertIn('002-susfs-old-kernel-sids.patch', commands)

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
