"""Run the actual SUSFS sucompat handlers from our pinned-source patch.

The policy doubles isolate the missing authorization boundary. This does not
replace a real kernel build or a target-app/device test.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/oneplus-9r/susfs-v2/003-sucompat-visibility-guards.patch'


def side(text, added):
    prefix = '+' if added else '-'
    return '\n'.join(line[1:] for line in text.splitlines()
                     if line.startswith(' ') or
                     (line.startswith(prefix) and not line.startswith(prefix * 3)))


def function(source, name):
    match = re.search(r'^(?:static )?(?:int|bool) ' + name +
                      r'\([^;]*?\)\s*\{.*?^\}', source, re.M | re.S)
    if not match:
        raise AssertionError(f'missing complete handler: {name}')
    return match.group()


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
typedef unsigned int uid_t;
typedef struct { uid_t val; } kuid_t;
struct filename { const char *name; };
#define READ_ONCE(x) (x)
#define likely(x) (x)
#define unlikely(x) (x)
#define IS_ERR(x) ((uintptr_t)(x) >= (uintptr_t)-4095)
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static const char su_path[] = "/system/bin/su";
static const char sh_path[] = "/system/bin/sh";
bool ksu_su_compat_enabled = true;
bool no_su, in_chroot;
kuid_t task_uid = {65534};
uid_t granted_uid = 12345;
int auth_calls;
bool susfs_is_current_proc_no_su(void) { return no_su; }
kuid_t current_uid(void) { return task_uid; }
bool __ksu_is_allow_uid_for_current(uid_t uid) {
    assert(uid == task_uid.val);
    ++auth_calls;
    return uid == granted_uid;
}
bool current_chrooted(void) { return in_chroot; }
'''

CASES = r'''
int main(void) {
    const uid_t uids[] = {0, 10119, 12345, 65534};
    const char *paths[] = {"/system/bin/su", "/system/bin/sh", "/other/file"};
    int dfd = -100, flags = 0, mode = 0;
    for (unsigned int i = 0; i < sizeof(uids)/sizeof(uids[0]); ++i)
    for (unsigned int grant = 0; grant < sizeof(uids)/sizeof(uids[0]); ++grant)
    for (int enabled = 0; enabled <= 1; ++enabled)
    for (int deny = 0; deny <= 1; ++deny)
    for (int chroot = 0; chroot <= 1; ++chroot)
    for (unsigned int path = 0; path < sizeof(paths)/sizeof(paths[0]); ++path)
    for (int stat = 0; stat <= 1; ++stat) {
        task_uid.val = uids[i]; granted_uid = uids[grant];
        ksu_su_compat_enabled = enabled; no_su = deny; in_chroot = chroot;
        char buffer[64]; strcpy(buffer, paths[path]);
        struct filename name = {buffer}; struct filename *ptr = &name;
        auth_calls = 0;
        int ret = stat ? ksu_handle_stat(&dfd, &ptr, &flags) :
                         ksu_handle_faccessat(&dfd, &ptr, &mode, &flags);
        assert(ret == 0 && ptr == &name);
        bool mapped = enabled && !deny && !chroot &&
                      task_uid.val == granted_uid && path == 0;
        const char *expected = mapped ? sh_path : paths[path];
        if (strcmp(buffer, expected)) return 42;
        if (!enabled || deny) assert(auth_calls == 0);
    }
    /* Errors and NULL names must not be dereferenced or rewritten. */
    ksu_su_compat_enabled = true; no_su = in_chroot = false;
    task_uid.val = granted_uid = 12345;
    struct filename *bad = (void *)(intptr_t)-14;
    assert(ksu_handle_stat(&dfd, &bad, &flags) == 0);
    assert(ksu_handle_faccessat(&dfd, &bad, &mode, &flags) == 0);
    struct filename empty = {NULL}; bad = &empty;
    assert(ksu_handle_stat(&dfd, &bad, &flags) == 0);
    assert(ksu_handle_faccessat(&dfd, &bad, &mode, &flags) == 0);
    assert(bad == &empty && empty.name == NULL);
    return 0;
}
'''


class SucompatVisibilityTests(unittest.TestCase):
    def compile_run(self, source, expected):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(source)
            built = subprocess.run(
                [os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                 '-fsanitize=undefined', str(path / 'test.c'), '-o', str(path / 'test')],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(path / 'test')], capture_output=True, text=True)
            self.assertEqual(run.returncode, expected, run.stdout + run.stderr)

    def test_original_handlers_reproduce_unprivileged_su_visibility(self):
        source = side(PATCH.read_text(), False)
        handlers = '\n'.join(function(source, name) for name in
                             ('ksu_handle_faccessat', 'ksu_handle_stat'))
        # Nonzero is intentional: the pre-fix implementation violates the
        # exact same policy matrix that the patched implementation must pass.
        self.compile_run(PRELUDE + handlers + CASES, 42)

    def test_patched_handlers_enforce_uid_feature_and_no_su_policy(self):
        source = side(PATCH.read_text(), True)
        handlers = '\n'.join(function(source, name) for name in
                             ('ksu_susfs_sucompat_path_allowed',
                              'ksu_handle_faccessat', 'ksu_handle_stat'))
        self.compile_run(PRELUDE + handlers + CASES, 0)

    def test_native_v2_build_applies_fix_without_relaxing_other_profiles(self):
        prep = (ROOT / 'scripts/prepare-susfs-v2.sh').read_text()
        self.assertIn('"$PORT/003-sucompat-visibility-guards.patch"', prep)
        self.assertIn('--fuzz=0', prep)
        workflow = (ROOT / '.github/workflows/build-oneplus-9r-sukisu-susfs.yml').read_text()
        self.assertIn('bash scripts/prepare-susfs-v2.sh', workflow)
        self.assertIn('"$PORT/"*.patch', prep)  # diagnostic input hashes
        source = side(PATCH.read_text(), True)
        self.assertIn('#ifdef CONFIG_KSU_SUSFS', source)
        self.assertNotIn('ksu_handle_execveat_sucompat', '\n'.join(
            line for line in PATCH.read_text().splitlines() if line.startswith('+')))


if __name__ == '__main__':
    unittest.main()
