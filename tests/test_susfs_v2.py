"""Native v2 provenance and executable mount/fsnotify lifecycle regressions."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'patches/oneplus-9r/susfs-v2'


def new_side(patch, filename):
    text = patch.read_text().split(f'diff --git a/{filename} b/{filename}\n')[1].split('diff --git ')[0]
    return '\n'.join(line[1:] for line in text.splitlines()
                     if line.startswith(' ') or (line.startswith('+') and not line.startswith('+++')))


def function(text, name):
    match = re.search(r'^[^\n]*\b' + name + r'\([^;]*?\)\s*\{', text, re.M)
    if not match:
        raise AssertionError(f'missing function: {name}')
    depth = 1
    end = match.end()
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end] + '\n'


class SusfsV2Tests(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(source)
            r = subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror',
                                '-fsanitize=undefined', str(p / 'test.c'), '-o', str(p / 'test')],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(p / 'test')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_native_sources_are_unmodified_upstream_not_v1_wrappers(self):
        lock = json.loads((ROOT / 'config/reference/oneplus-9r-susfs-v2-lock.json').read_text())
        self.assertEqual(lock['version'], 'v2.4.0')
        for path, expected in lock['files'].items():
            data = (PORT / 'upstream' / path.removeprefix('kernel_patches/')).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected, path)
        patch = (PORT / '50_add_susfs_in_kernel-4.19.patch').read_text()
        self.assertNotIn('susfs_mnt_id_backup', patch)
        self.assertNotIn('susfs_mnt_id_ida', patch)
        self.assertIn('#include "internal.h"', new_side(PORT / '50_add_susfs_in_kernel-4.19.patch', 'fs/stat.c'))
        prep = (ROOT / 'scripts/prepare-susfs-v2.sh').read_text()
        self.assertIn('test ! -e "$KERNEL_DIR/fs/susfs_compat.c"', prep)
        self.assertIn('--fuzz=0', prep)
        compat = (PORT / '001-core-4.19.patch').read_text()
        self.assertIn('+#include <linux/cred.h>', compat)
        self.assertIn('+#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER', compat)

    def test_mount_ids_borrowed_owned_inheritance_and_error_unwind(self):
        ns = new_side(PORT / '50_add_susfs_in_kernel-4.19.patch', 'fs/namespace.c')
        funcs = ''.join(function(ns, name) for name in (
            'mnt_free_id', 'susfs_alloc_unshare_ksu_vfsmnt', 'susfs_alloc_non_unshare_ksu_vfsmnt'))
        begin = ns.index('\tmnt->mnt.mnt_flags = old->mnt.mnt_flags;')
        end = ns.index('\n#endif', begin) + len('\n#endif')
        inheritance = ns[begin:end]
        for smp in (False, True):
            source = ('#define CONFIG_SMP 1\n' if smp else '') + r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define CONFIG_KSU_SUSFS_SUS_MOUNT 1
#define DEFAULT_KSU_MNT_ID 2000000000
#define VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT 0x80000000U
#define MNT_WRITE_HOLD 1
#define MNT_MARKED 2
#define MNT_INTERNAL 4
#define GFP_KERNEL 0
#define GFP_KERNEL_ACCOUNT 0
#define unlikely(x) (x)
#define INIT_HLIST_NODE(x) ((void)(x))
#define INIT_LIST_HEAD(x) ((void)(x))
struct pin { int initialized; };
struct mnt_pcp { int mnt_count; };
struct mount {
    int mnt_id;
    struct { unsigned mnt_flags; } mnt;
    char *mnt_devname;
    struct mnt_pcp *mnt_pcp;
    int mnt_count, mnt_writers;
    int mnt_hash, mnt_child, mnt_mounts, mnt_list, mnt_expire, mnt_share;
    int mnt_slave_list, mnt_slave, mnt_mp_list, mnt_umounting;
    struct pin mnt_umount;
};
static int mnt_cache, mnt_id_ida, fail_stage, owned_id, live_id, live_mounts, live_names, live_pcp;
static int allocations, releases;
static void *kmem_cache_zalloc(int cache, int flags) {
    if (fail_stage == 1) return NULL;
    ++live_mounts; return calloc(1, sizeof(struct mount));
}
static void kmem_cache_free(int cache, void *p) { --live_mounts; free(p); }
static char *kstrdup_const(const char *name, int flags) {
    if (fail_stage == 2) return NULL;
    ++live_names; return strdup(name);
}
static void kfree_const(char *name) { if (name) { --live_names; free(name); } }
static __attribute__((unused)) void *pcp_alloc(void) {
    if (fail_stage == 3) return NULL;
    ++live_pcp; return calloc(1, sizeof(struct mnt_pcp));
}
#define alloc_percpu(type) pcp_alloc()
#define this_cpu_add(x,n) ((x) += (n))
static int ida_alloc_min(int *pool, int minimum, int flags) {
    assert(pool == &mnt_id_ida);
    if (fail_stage == 4) return -ENOSPC;
    assert(!live_id); live_id = 1; owned_id = minimum + allocations++;
    return owned_id;
}
static void ida_free(int *pool, int id) {
    assert(pool == &mnt_id_ida && live_id && id == owned_id);
    live_id = 0; ++releases;
}
static void drop_mountpoint(void) {}
#define init_fs_pin(p,f) ((void)(f), (p)->initialized = 1)
'''
            source += funcs
            source += '\nstatic void inherit(struct mount *mnt, struct mount *old, bool is_mnt_ksu_unshared) {\n' + inheritance + '\n}\n'
            source += r'''
static void release(struct mount *m) {
    mnt_free_id(m);
#ifdef CONFIG_SMP
    if (m->mnt_pcp) { --live_pcp; free(m->mnt_pcp); }
#endif
    kfree_const(m->mnt_devname); kmem_cache_free(mnt_cache, m);
}
static void no_leaks(void) { assert(!live_id && !live_mounts && !live_names && !live_pcp); }
int main(void) {
    struct mount parent = {.mnt = {.mnt_flags = VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT | MNT_INTERNAL}};
    struct mount *m;
    int id, mode, before;
    /* Borrow ID 0 and other caller-owned IDs: no IDA allocation/free. */
    int borrowed[] = {0, 101, 300, DEFAULT_KSU_MNT_ID + 123};
    for (unsigned i = 0; i < sizeof(borrowed)/sizeof(borrowed[0]); ++i) {
        for (mode = 0; mode < 2; ++mode) {
            before = releases; m = susfs_alloc_unshare_ksu_vfsmnt("test", borrowed[i]);
            assert(m && m->mnt_id == borrowed[i] && m->mnt_umount.initialized);
            if (mode) inherit(m, &parent, true);
            /* mode=0 simulates clone failing BEFORE flag inheritance. */
            release(m); assert(releases == before); no_leaks();
        }
    }
    /* A new owning clone must not inherit the parent's borrow marker. */
    for (int n = 0; n < 10000; ++n) {
        m = susfs_alloc_non_unshare_ksu_vfsmnt("test");
        assert(m && m->mnt_umount.initialized); id = m->mnt_id;
        inherit(m, &parent, false);
        assert(m->mnt_id == id && !(m->mnt.mnt_flags & VFSMOUNT_MNT_FLAGS_KSU_UNSHARED_MNT));
        release(m); no_leaks();
    }
    for (fail_stage = 1; fail_stage <= 4; ++fail_stage) {
#ifndef CONFIG_SMP
        if (fail_stage == 3) continue;
#endif
        m = susfs_alloc_non_unshare_ksu_vfsmnt("test");
        assert(!m); no_leaks();
        if (fail_stage != 4) {
            before = releases; m = susfs_alloc_unshare_ksu_vfsmnt("test", 0);
            assert(!m && releases == before); no_leaks();
        }
    }
    return 0;
}
'''
            with self.subTest(smp=smp):
                self.compile_run(source)

    def test_419_fsnotify_adapter_preserves_deferred_srcu_cleanup(self):
        core = (PORT / 'upstream/fs/susfs.c').read_text()
        adapter = new_side(PORT / '001-core-4.19.patch', 'fs/susfs.c')
        source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
typedef unsigned int u32;
struct inode {int unused;}; struct fsnotify_mark {int unused;};
struct fsnotify_group {int unused;}; struct fsnotify_iter_info {int unused;};
struct work_struct {int unused;}; struct delayed_work {int unused;};
struct qstr {const unsigned char *name; unsigned len;};
struct path {void *mnt;};
struct watch_dir {struct inode *inode; struct path kpath;} g_watch;
static struct fsnotify_group group, *g = &group;
static struct inode inode;
static struct delayed_work sdcard_cleanup_dwork;
static unsigned long sdcard_cleanup_scheduled;
static bool susfs_is_sdcard_android_data_not_decrypted = true;
static int queued, destroyed, inode_puts, path_puts, in_callback;
#define HZ 100
#define system_unbound_wq 1
#define SUSFS_LOGI(...) ((void)0)
#define static_key_enabled(p) (*(p))
#define static_branch_disable(p) (*(p) = false)
#define xchg(p,v) ({ __typeof__(*(p)) old = *(p); *(p) = (v); old; })
static int test_and_set_bit(int n, unsigned long *v) { int old = *v & (1UL<<n); *v |= 1UL<<n; return old; }
static void queue_delayed_work(int queue, struct delayed_work *work, int delay) {
    assert(in_callback && delay == 5*HZ); ++queued;
}
static void fsnotify_destroy_group(struct fsnotify_group *grp) { assert(!in_callback); ++destroyed; }
static void iput(struct inode *i) { ++inode_puts; }
static void path_put(struct path *p) { ++path_puts; }
'''
        source += function(core, 'susfs_sdcard_cleanup_fn')
        source += function(core, 'susfs_handle_sdcard_inode_event')
        source += function(adapter, 'susfs_handle_sdcard_event')
        source += r'''
int main(void) {
    g_watch.inode = &inode; g_watch.kpath.mnt = &group;
    in_callback = 1;
    susfs_handle_sdcard_event(&group, &inode, 0, NULL, 0, NULL, 0, NULL);
    susfs_handle_sdcard_event(&group, &inode, 0, NULL, 0, (const unsigned char *)"AndroidX", 0, NULL);
    assert(!queued && !destroyed);
    susfs_handle_sdcard_event(&group, &inode, 0, NULL, 0, (const unsigned char *)"Android", 0, NULL);
    susfs_handle_sdcard_event(&group, &inode, 0, NULL, 0, (const unsigned char *)"Android", 0, NULL);
    assert(queued == 1 && !destroyed && susfs_is_sdcard_android_data_not_decrypted);
    in_callback = 0;
    susfs_sdcard_cleanup_fn(NULL); susfs_sdcard_cleanup_fn(NULL);
    assert(destroyed == 1 && inode_puts == 1 && path_puts == 1);
    assert(!g && !g_watch.inode && !g_watch.kpath.mnt && !susfs_is_sdcard_android_data_not_decrypted);
    return 0;
}
'''
        self.compile_run(source)


if __name__ == '__main__':
    unittest.main()
