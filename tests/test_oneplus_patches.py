"""Compile actual patch functions against small userspace kernel API doubles.

These check ABI boundaries and hook forwarding, not device boot behaviour.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'patches/oneplus-9r'
CORE = (PATCHES / 'fs/susfs.c').read_text()
COMPAT = (PATCHES / 'fs/susfs_compat.c').read_text()
HEADER = (PATCHES / 'include/linux/susfs.h').read_text()
FLAGS = (PATCHES / 'include/linux/susfs_def.h').read_text()


def function(source, name):
    match = re.search(r'^(?:static inline |static )?(?:int|void|bool) ' + name +
                      r'\([^;]*?\)\s*\{.*?^\}', source, re.M | re.S)
    if not match:
        raise AssertionError(f'missing function: {name}')
    return match.group()


def structure(source, name):
    return re.search(r'struct ' + name + r' \{.*?\n\};', source, re.S).group()


class PatchTests(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'probe.c').write_text(source)
            result = subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                            '-fsanitize=undefined', '-g', str(path / 'probe.c'),
                            '-o', str(path / 'probe')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(path / 'probe')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_v1_v2_translation_and_bounds(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define __user
#define SUSFS_MAX_LEN_PATHNAME 256
#define LOOKUP_FOLLOW 1
#define pr_warn(...) ((void)0)
static int copy_fault, helper_result, calls;
static int copy_from_user(void *to, const void *from, size_t n) {
    if (copy_fault) return 1;
    memcpy(to, from, n); return 0;
}
#define put_user(value, ptr) (*(ptr) = (value))
#define strlcpy test_strlcpy
static size_t strlcpy(char *to, const char *from, size_t n) {
    size_t len = strlen(from); snprintf(to, n, "%s", from); return len;
}
struct inode { unsigned long i_ino; };
struct dentry { struct inode *d_inode; };
struct path { struct dentry *dentry; };
static struct inode inode = {42};
static struct dentry dentry = {&inode};
static int kern_path(const char *name, int flags, struct path *p) {
    if (!strcmp(name, "/missing")) return -ENOENT;
    p->dentry = &dentry; return 0;
}
static void path_put(struct path *p) {}
'''
        for typ in ('sus_path', 'sus_kstat', 'open_redirect'):
            source += structure(HEADER, 'st_susfs_' + typ) + '\n'
        for typ in ('sus_path', 'sus_kstat', 'open_redirect'):
            source += structure(COMPAT, 'compat_v2_' + typ) + '\n'
        source += r'''
static struct st_susfs_sus_path captured_path;
static struct st_susfs_sus_kstat captured_kstat;
static struct st_susfs_open_redirect captured_redirect;
int susfs_add_sus_path_kernel(const struct st_susfs_sus_path *p) {
    captured_path = *p; ++calls; return helper_result;
}
int susfs_add_sus_kstat_kernel(const struct st_susfs_sus_kstat *p) {
    captured_kstat = *p; ++calls; return helper_result;
}
int susfs_update_sus_kstat_kernel(const struct st_susfs_sus_kstat *p) {
    captured_kstat = *p; ++calls; return helper_result;
}
int susfs_add_open_redirect_kernel(const struct st_susfs_open_redirect *p) {
    captured_redirect = *p; ++calls; return helper_result;
}
'''
        for name in ('compat_add_sus_path', 'susfs_add_sus_path', 'susfs_add_sus_path_loop',
                     'compat_fill_v155_kstat', 'compat_kstat_common', 'susfs_add_sus_kstat',
                     'susfs_update_sus_kstat', 'susfs_add_open_redirect'):
            source += function(COMPAT, name) + '\n'
        for name in ('add_sus_path', 'add_sus_kstat', 'update_sus_kstat', 'add_open_redirect'):
            source += function(CORE, 'susfs_v159_' + name) + '\n'
        source += r'''
int main(void) {
    struct { struct compat_v2_sus_path req; unsigned char guard[32]; } p;
    struct compat_v2_sus_path expected;
    struct compat_v2_sus_kstat k = {0}, original;
    struct compat_v2_open_redirect r = {0}, original_r;
    void *user;
    size_t i;
    memset(&p, 0xa5, sizeof(p));
    strcpy(p.req.target_pathname, "/test/path");
    expected = p.req; expected.err = -ENOENT;
    helper_result = -ENOENT; user = &p.req;
    susfs_add_sus_path(&user);
    assert(!memcmp(&expected, &p.req, sizeof(expected)));
    for (i = 0; i < sizeof(p.guard); ++i) assert(p.guard[i] == 0xa5);
    assert(!strcmp(captured_path.target_pathname, "/test/path"));
    assert(calls == 1);
    memset(p.req.target_pathname, 'x', sizeof(p.req.target_pathname));
    susfs_add_sus_path(&user); assert(p.req.err == -EINVAL && calls == 1);
    copy_fault = 1; susfs_add_sus_path(&user);
    assert(p.req.err == -EFAULT && calls == 1); copy_fault = 0;
    susfs_add_sus_path(NULL); user = NULL; susfs_add_sus_path(&user);

    strcpy(k.target_pathname, "/test/stat");
    k.target_ino = 7; k.spoofed_ino = 8; k.spoofed_dev = 9;
    k.spoofed_atime_tv_sec = 11; k.spoofed_atime_tv_nsec = 12;
    k.spoofed_mtime_tv_sec = 21; k.spoofed_mtime_tv_nsec = 22;
    k.spoofed_ctime_tv_sec = 31; k.spoofed_ctime_tv_nsec = 32;
    original = k; original.err = -ENOENT; user = &k;
    susfs_add_sus_kstat(&user);
    assert(!memcmp(&k, &original, sizeof(k)));
    assert(captured_kstat.spoofed_atime_tv_sec == 11);
    assert(captured_kstat.spoofed_atime_tv_nsec == 12);
    assert(captured_kstat.spoofed_mtime_tv_sec == 21);
    assert(captured_kstat.spoofed_mtime_tv_nsec == 22);
    assert(captured_kstat.spoofed_ctime_tv_sec == 31);
    assert(captured_kstat.spoofed_ctime_tv_nsec == 32);
    helper_result = 0; susfs_update_sus_kstat(&user); assert(k.err == 0);

    strcpy(r.target_pathname, "/test/source");
    strcpy(r.redirected_pathname, "/test/dest");
    original_r = r; original_r.err = 0; user = &r;
    susfs_add_open_redirect(&user);
    assert(!memcmp(&r, &original_r, sizeof(r)));
    assert(captured_redirect.target_ino == 42);
    assert(!strcmp(captured_redirect.redirected_pathname, "/test/dest"));
    strcpy(r.target_pathname, "/missing");
    susfs_add_open_redirect(&user); assert(r.err == -ENOENT);
    helper_result = -EINVAL;
    assert(susfs_v159_add_sus_path(&captured_path) == -EINVAL);
    assert(susfs_v159_add_sus_kstat(&captured_kstat) == -EINVAL);
    assert(susfs_v159_update_sus_kstat(&captured_kstat) == -EINVAL);
    assert(susfs_v159_add_open_redirect(&captured_redirect) == -EINVAL);
    return 0;
}
'''
        self.compile_run(source)

    def test_classification_is_independent_of_umount_bit(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#define BIT(n) (1UL << (n))
#define READ_ONCE(x) (x)
#define TASK_STRUCT_NON_ROOT_USER_APP_PROC BIT(24)
struct task { unsigned long susfs_task_state, flags; } task;
#define current (&task)
'''
        source += function(FLAGS, 'susfs_is_current_non_root_user_app_proc') + '\n'
        source += function(FLAGS, 'susfs_set_current_non_root_user_app_proc') + '\n'
        source += r'''
int main(void) {
    task.flags = BIT(33);
    assert(!susfs_is_current_non_root_user_app_proc());
    task.flags = 0;
    susfs_set_current_non_root_user_app_proc();
    assert(susfs_is_current_non_root_user_app_proc());
    assert(task.flags == 0);
    return 0;
}
'''
        self.compile_run(source)

    def test_kstat_locked_regions_do_not_sleep(self):
        for name in ('susfs_add_sus_kstat_kernel', 'susfs_update_sus_kstat_kernel',
                     'susfs_sus_ino_for_generic_fillattr', 'susfs_sus_ino_for_show_map_vma'):
            body = function(CORE, name)
            locked = body.split('spin_lock(&susfs_spin_lock);', 1)[1].split('spin_unlock', 1)[0]
            for forbidden in ('GFP_KERNEL', 'kern_path(', 'susfs_update_sus_kstat_inode(',
                              'copy_from_user(', 'return'):
                self.assertNotIn(forbidden, locked, name)

    def test_added_preprocessor_endings_do_not_swallow_statements(self):
        for path in PATCHES.rglob('*.patch'):
            for line in path.read_text().splitlines():
                if re.match(r'^\+#\s*(endif|else)\b', line):
                    tail = re.sub(r'^\+#\s*(endif|else)\b', '', line)
                    tail = re.sub(r'/\*.*?\*/|//.*', '', tail).strip()
                    self.assertEqual(tail, '', f'{path}: {line}')

    def test_susfs_mount_success_is_not_an_unconditional_enomem(self):
        text = (PATCHES / '50_add_susfs_in_kernel-4.19.patch').read_text()
        section = text.split('diff --git a/fs/namespace.c b/fs/namespace.c\n')[1].split('diff --git ')[0]
        hunk = next(part for part in re.split(r'^@@.*@@.*$', section, flags=re.M)
                    if 'alloc_vfsmnt(fc->source' in part)
        new = '\n'.join(line[1:] for line in hunk.splitlines()
                        if (line.startswith('+') and not line.startswith('+++')) or line.startswith(' '))
        end = '\t\treturn ERR_PTR(-ENOMEM);'
        body = new[new.index('#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT'):new.index(end) + len(end)]
        for enabled in (False, True):
            source = ('#define CONFIG_KSU_SUSFS_SUS_MOUNT 1\n' if enabled else '') + r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#define unlikely(x) (x)
#define ERR_PTR(x) ((struct mount *)(long)(x))
struct mount { int unused; } good_mount;
struct fs_context { const char *source; };
static bool ksu, fail_alloc;
static int allocations;
static bool __attribute__((unused)) susfs_is_current_ksu_domain(void) { return ksu; }
static struct mount *alloc_vfsmnt(const char *source, ...) {
    assert(source); ++allocations; return fail_alloc ? NULL : &good_mount;
}
static struct mount *probe(struct fs_context *fc) {
    struct mount *mnt;
'''
            source += body + '\nreturn mnt;\n}\n'
            source += r'''
int main(void) {
    struct fs_context fc = {NULL};
    int domain, failure;
    for (domain = 0; domain < 2; ++domain) {
        for (failure = 0; failure < 2; ++failure) {
            ksu = domain; fail_alloc = failure; allocations = 0;
            assert(probe(&fc) == (failure ? ERR_PTR(-ENOMEM) : &good_mount));
            assert(allocations == 1);
        }
    }
    return 0;
}
'''
            self.compile_run(source)

    def test_susfs_queries_and_unsupported_v2_controls(self):
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define __user
#define SUSFS_MAX_LEN_PATHNAME 256
#define SUSFS_ENABLED_FEATURES_SIZE 8192
#define SUSFS_VERSION "v1.5.9-v2compat"
#define SUSFS_VARIANT "NON-GKI"
#define CONFIG_KSU_SUSFS_SUS_PATH 1
#define CONFIG_KSU_SUSFS_SUS_KSTAT 1
#define CONFIG_KSU_SUSFS_SPOOF_UNAME 1
#define CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG 1
#define CONFIG_KSU_SUSFS_OPEN_REDIRECT 1
#define scnprintf snprintf
#define put_user(value, ptr) (*(ptr) = (value))
#define strlcpy(to, from, n) snprintf(to, n, "%s", from)
static int copy_fault;
static __attribute__((warn_unused_result)) int copy_to_user(void *to, const void *from, size_t n) {
    if (copy_fault) return 1;
    memcpy(to, from, n); return 0;
}
'''
        for name in ('enabled_features', 'variant', 'version', 'sus_map',
                     'hide_sus_mnts_for_non_su_procs', 'avc_log_spoofing'):
            source += structure(HEADER, 'st_susfs_' + name) + '\n'
        for name in ('get_enabled_features', 'show_variant', 'show_version',
                     'set_hide_sus_mnts_for_non_su_procs', 'add_sus_map', 'set_avc_log_spoofing'):
            source += function(COMPAT, 'susfs_' + name) + '\n'
        source += r'''
int main(void) {
    struct st_susfs_version version = {.err = -123};
    struct st_susfs_variant variant = {.err = -123};
    struct st_susfs_enabled_features features = {.err = -123};
    struct st_susfs_sus_map map = {.err = -123};
    struct st_susfs_avc_log_spoofing avc = {.enabled = true, .err = -123};
    struct st_susfs_hide_sus_mnts_for_non_su_procs mount = {.enabled = true, .err = -123};
    void *user = &version;
    susfs_show_version(&user);
    assert(version.err == 0 && !strcmp(version.susfs_version, SUSFS_VERSION));
    user = &variant; susfs_show_variant(&user);
    assert(variant.err == 0 && !strcmp(variant.susfs_variant, "NON-GKI"));
    user = &features; susfs_get_enabled_features(&user);
    assert(features.err == 0 && strstr(features.enabled_features, "sus_path"));
    assert(!strstr(features.enabled_features, "sus_map"));
    copy_fault = 1; susfs_get_enabled_features(&user);
    assert(features.err == -EFAULT);
    user = &map; susfs_add_sus_map(&user); assert(map.err == -EOPNOTSUPP);
    user = &avc; susfs_set_avc_log_spoofing(&user);
    assert(avc.enabled && avc.err == -EOPNOTSUPP);
    user = &mount; susfs_set_hide_sus_mnts_for_non_su_procs(&user);
    assert(mount.enabled && mount.err == -EOPNOTSUPP);
    user = NULL; susfs_show_version(&user); susfs_add_sus_map(&user);
    susfs_get_enabled_features(NULL);
    return 0;
}
'''
        self.compile_run(source)

    def test_modern_hooks_consume_modified_filenames(self):
        for path in (PATCHES / 'kernel_hooks').glob('*.patch'):
            text = path.read_text()
            self.assertNotIn('(int *)AT_FDCWD', text)
            self.assertNotIn('ksu_name', text)  # obsolete discarded temporary
            self.assertIn('+\t\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);', text)
            self.assertIn('return __do_execve_file(fd, filename, argv, envp, flags, NULL);', text)
            self.assertIn('+\t\tres = filename_lookup(dfd, name, lookup_flags, &path, NULL);', text)
            self.assertIn('+\t\terror = filename_lookup(dfd, name, lookup_flags, &path, NULL);', text)
            self.assertNotIn('+\t\tputname(', text)
            self.assertIn('getname_flags(filename, lookup_flags, NULL)', text)

    def test_hook_forwarding_native(self):
        for path in (PATCHES / 'kernel_hooks').glob('*.patch'):
            text = path.read_text()
            # Reconstruct the new side of each diff, including context lines.
            def new_side(file, marker=None):
                section = text.split(f'diff --git a/{file} b/{file}\n')[1].split('diff --git ')[0]
                if marker:
                    section = next(part for part in re.split(r'^@@.*@@.*$', section, flags=re.M)
                                   if marker in part)
                return '\n'.join(line[1:] for line in section.splitlines()
                                 if (line.startswith('+') and not line.startswith('+++'))
                                 or line.startswith(' '))
            opening = new_side('fs/open.c')
            opening = opening[opening.index('#ifdef CONFIG_KSU'):opening.index('\n\tif (res)')]
            stat = new_side('fs/stat.c', 'getname_flags')
            stat = stat[stat.index('#ifdef CONFIG_KSU'):stat.index('\n\tif (error)')]
            execve = new_side('fs/exec.c')
            execve = execve[execve.index('#ifdef CONFIG_KSU'):execve.index('\n}')]
            source = r'''
#include <assert.h>
#include <string.h>
#include <stddef.h>
#define CONFIG_KSU 1
#define CONFIG_KSU_SUSFS 1
#define IS_ERR(x) ((x) == NULL)
struct filename { char *name; };
struct path { int unused; };
struct user_arg_ptr { int token; };
static char buffer[64];
static struct filename scratch = {buffer};
static int consumed;
struct filename *getname_flags(const char *s, unsigned int f, void *p) {
    strcpy(buffer, s); return &scratch;
}
int filename_lookup(int dfd, struct filename *name, unsigned int flags,
                    struct path *p, void *root) {
    assert(!strcmp(name->name, "/system/bin/sh")); ++consumed; return 0;
}
int ksu_handle_faccessat(int *dfd, struct filename **name, int *mode, int *flags) {
    strcpy((*name)->name, "/system/bin/sh"); return 0;
}
int ksu_handle_stat(int *dfd, struct filename **name, int *flags) {
    strcpy((*name)->name, "/system/bin/sh"); return 0;
}
int ksu_handle_execveat(int *fd, struct filename **name, void *argv, void *envp, int *flags) {
    assert(fd && flags); *fd = 9; *flags = 17; return 0;
}
int __do_execve_file(int fd, struct filename *name, struct user_arg_ptr argv,
                     struct user_arg_ptr envp, int flags, void *file) {
    assert(fd == 9 && flags == 17); return argv.token;
}
'''
            source += 'int access_probe(int dfd, const char *filename, int mode) {\nint res; unsigned int lookup_flags=0; struct path path;\n' + opening + '\nreturn res;\n}\n'
            source += 'int stat_probe(int dfd, const char *filename, int flags) {\nint error; unsigned int lookup_flags=0; struct path path;\n' + stat + '\nreturn error;\n}\n'
            source += 'int exec_probe(int fd, struct filename *filename, struct user_arg_ptr argv, struct user_arg_ptr envp, int flags) {\n' + execve + '\n}\n'
            source += r'''
int main(void) {
    struct user_arg_ptr native = {64}, compat = {32};
    assert(access_probe(1, "/system/bin/su", 0) == 0);
    assert(stat_probe(1, "/system/bin/su", 0) == 0);
    assert(consumed == 2);
    assert(exec_probe(-100, &scratch, native, native, 0) == 64);
    assert(exec_probe(-100, &scratch, compat, compat, 0) == 32);
    return 0;
}
'''
            self.compile_run(source)

    def test_minimal_non_susfs_path_and_fstat_hooks(self):
        text = (PATCHES / 'minimal_hooks/kernel-4.19-sukisu.patch').read_text()
        def hunk(file, marker):
            section = text.split(f'diff --git a/{file} b/{file}\n')[1].split('diff --git ')[0]
            selected = next(part for part in re.split(r'^@@.*@@.*$', section, flags=re.M)
                            if marker in part)
            return '\n'.join(line[1:] for line in selected.splitlines()
                             if (line.startswith('+') and not line.startswith('+++'))
                             or line.startswith(' '))
        opening = hunk('fs/open.c', 'getname_flags')
        opening = opening[opening.index('#ifdef CONFIG_KSU'):opening.index('\n\tif (res)')]
        stat = hunk('fs/stat.c', 'getname_flags')
        stat = stat[stat.index('#ifdef CONFIG_KSU'):stat.index('\n\tif (error)')]
        fdstat = hunk('fs/stat.c', 'ksu_handle_vfs_fstat')
        fdstat = fdstat[fdstat.index('#ifdef CONFIG_KSU'):fdstat.index('#endif') + len('#endif')]
        source = r'''
#include <assert.h>
#include <string.h>
#define CONFIG_KSU 1
#define __user
#define STATX_SIZE 0x200
typedef long long loff_t;
struct path { int unused; };
struct kstat { unsigned int result_mask; loff_t size; };
static int path_calls, stat_calls;
int user_path_at(int fd, const char *filename, unsigned int flags, struct path *path) {
    assert(!strcmp(filename, "/system/bin/sh")); ++path_calls; return 0;
}
int ksu_handle_faccessat(int *fd, const char **filename, int *mode, int *flags) {
    *filename = "/system/bin/sh"; return 0;
}
int ksu_handle_stat(int *fd, const char **filename, int *flags) {
    *filename = "/system/bin/sh"; return 0;
}
void ksu_handle_vfs_fstat(int fd, loff_t *size) { *size += 42; ++stat_calls; }
'''
        source += 'int access_probe(int dfd, const char *filename, int mode) {\nint res; unsigned int lookup_flags=0; struct path path;\n' + opening + '\nreturn res;\n}\n'
        source += 'int stat_probe(int dfd, const char *filename, int flags) {\nint error; unsigned int lookup_flags=0; struct path path;\n' + stat + '\nreturn error;\n}\n'
        source += 'void fstat_probe(int fd, int error, struct kstat *stat) {\n' + fdstat + '\n}\n'
        source += r'''
int main(void) {
    struct kstat stat = {STATX_SIZE, 10};
    assert(access_probe(0, "/system/bin/su", 0) == 0);
    assert(stat_probe(0, "/system/bin/su", 0) == 0);
    assert(path_calls == 2);
    fstat_probe(1, -1, &stat); assert(stat_calls == 0 && stat.size == 10);
    stat.result_mask = 0;
    fstat_probe(1, 0, &stat); assert(stat_calls == 0 && stat.size == 10);
    stat.result_mask = STATX_SIZE;
    fstat_probe(1, 0, &stat); assert(stat_calls == 1 && stat.size == 52);
    return 0;
}
'''
        self.compile_run(source)


if __name__ == '__main__':
    unittest.main()
