"""Executable contracts for the experimental absolute-file core (not device E2E)."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'patches/oneplus-9r/zeromount'
CORE = (PORT / 'fs/zeromount.c').read_text()
HEADER = (PORT / 'include/linux/zeromount.h').read_text()


def function(source, name):
    match = re.search(r'^.*\b' + name + r'\([^;]*?\)\s*\{', source, re.M)
    if not match:
        raise AssertionError(name)
    start = source.index('{', match.start())
    depth = 0
    for end in range(start, len(source)):
        if source[end] == '{': depth += 1
        elif source[end] == '}': depth -= 1
        if depth == 0: return source[match.start():end + 1]
    raise AssertionError('unclosed function ' + name)


class ZeroMountTests(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'probe.c').write_text(source)
            r = subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                                '-fsanitize=undefined', str(p / 'probe.c'), '-o', str(p / 'probe')],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([str(p / 'probe')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_provenance_and_isolated_profile(self):
        lock = json.loads((ROOT / 'config/reference/oneplus-9r-zeromount-lock.json').read_text())
        self.assertEqual(lock['commit'], 'c2cb71614868fe742cbffee2b6f3126523432673')
        for name, digest in lock['files'].items():
            self.assertEqual(hashlib.sha256((PORT / 'upstream' / name).read_bytes()).hexdigest(), digest)
        stable = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-susfs-overrides.json').read_text())
        candidate = json.loads((ROOT / 'config/reference/oneplus-9r-sukisu-zeromount-overrides.json').read_text())
        self.assertEqual(candidate, dict(stable, CONFIG_ZEROMOUNT='y'))
        for name in ['build-oneplus-9r-sukisu-susfs.yml', 'build-oneplus-9r-sukisu-kpm.yml']:
            self.assertNotIn('prepare-zeromount', (ROOT / '.github/workflows' / name).read_text())
        wf = (ROOT / '.github/workflows/build-oneplus-9r-sukisu-zeromount.yml').read_text()
        self.assertIn('contents: read', wf)
        self.assertNotIn('contents: write', wf)
        self.assertIn('bash scripts/prepare-zeromount.sh', wf)
        self.assertIn('fs/zeromount.o fs/namei.o', wf)

    def test_integration_has_no_permission_or_metadata_bypass(self):
        patch = (PORT / '001-core-hooks-4.19.patch').read_text()
        self.assertEqual(set(re.findall(r'^diff --git a/(\S+) b/', patch, re.M)),
                         {'fs/Kconfig', 'fs/Makefile', 'fs/namei.c', 'arch/arm64/include/asm/thread_info.h'})
        self.assertIn('default n', patch)
        self.assertNotIn('inode_permission', patch)
        self.assertNotIn('generic_permission', patch)
        self.assertNotIn('journal_info =', CORE + HEADER)
        self.assertNotIn('zm_bloom', CORE)
        self.assertNotIn('copy_to_user', function(CORE, 'zeromount_getname_hook'))
        self.assertIn('ATOMIC_INIT(0)', CORE)
        self.assertIn('0x04190001', HEADER)

    def test_path_and_file_validation(self):
        s = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <sys/stat.h>
typedef struct { unsigned int val; } kuid_t;
#define GLOBAL_ROOT_UID ((kuid_t){0})
static bool uid_eq(kuid_t a, kuid_t b) { return a.val == b.val; }
struct inode { unsigned int i_mode; kuid_t i_uid; };
struct path { void *dentry; };
static struct inode node;
static int puts;
static int kern_path(const char *p, unsigned int flags, struct path *out) {
    assert(flags == 0); out->dentry = &node;
    return !strcmp(p, "/missing") ? -ENOENT : 0;
}
static struct inode *d_backing_inode(void *d) { return d; }
static void path_put(struct path *p) { puts++; }
'''
        s += function(CORE, 'zm_valid_path') + '\n' + function(CORE, 'zm_validate_file')
        s += r'''
int main(void) {
    const char *bad[] = {NULL,"","relative","/","/a/","/a//b","/a/./b","/a/../b","/a/.","/a/.."};
    for (unsigned int i=0; i<sizeof(bad)/sizeof(bad[0]);i++) assert(!zm_valid_path(bad[i]));
    assert(zm_valid_path("/system/etc/test")); assert(zm_valid_path("/etc/test"));
    node.i_uid.val=0; node.i_mode=S_IFREG|0644;
    assert(zm_validate_file("/system/etc/test")==0 && puts==1);
    assert(zm_validate_file("/missing")==-ENOENT);
    node.i_uid.val=10123; assert(zm_validate_file("/file")==-EACCES);
    node.i_uid.val=0; node.i_mode=S_IFREG|0664; assert(zm_validate_file("/file")==-EACCES);
    node.i_mode=S_IFREG|0600; assert(zm_validate_file("/file")==-EACCES);
    node.i_mode=S_IFLNK|0777; assert(zm_validate_file("/file")==-EACCES);
    node.i_mode=S_IFDIR|0755; assert(zm_validate_file("/file")==-EACCES);
    return 0;
}
'''
        self.compile_run(s)

    def test_task_policy_and_recursion(self):
        s = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef unsigned int uid_t;
typedef struct { uid_t val; } kuid_t;
struct task { void *mm; void *journal_info; unsigned int flags; } task;
#define current (&task)
#define PF_KTHREAD 1U
#define PF_EXITING 2U
#define TIF_ZEROMOUNT 36
static uint64_t bits;
#define set_thread_flag(n) (bits |= (UINT64_C(1) << (n)))
#define clear_thread_flag(n) (bits &= ~(UINT64_C(1) << (n)))
#define test_thread_flag(n) ((bits & (UINT64_C(1) << (n))) != 0)
static int zm_enabled;
#define atomic_read(p) (*(p))
static uid_t uid;
static bool granted, umounted;
static kuid_t current_uid(void) { return (kuid_t){uid}; }
static bool susfs_is_current_proc_umounted(void) { return umounted; }
bool __ksu_is_allow_uid_for_current(uid_t u) { assert(u==uid); return granted; }
'''
        for n in ['zm_enter', 'zm_exit', 'zm_is_recursive']:
            s += function(HEADER, n) + '\n'
        s += function(CORE, 'zm_app_allowed')
        s += r'''
int main(void) {
    task.mm=&task; uid=10123;
    assert(!zm_app_allowed()); zm_enabled=1; assert(zm_app_allowed());
    uid=110123; assert(zm_app_allowed()); /* secondary-user app */
    uid=1000; assert(!zm_app_allowed()); uid=101000; assert(!zm_app_allowed());
    uid=0; assert(!zm_app_allowed()); uid=10123;
    granted=true; assert(!zm_app_allowed()); granted=false;
    umounted=true; assert(!zm_app_allowed()); umounted=false;
    task.journal_info=&task; assert(!zm_app_allowed());
    zm_enter(); assert(zm_is_recursive()); assert(task.journal_info==&task);
    zm_exit(); assert(!zm_is_recursive()); assert(task.journal_info==&task);
    task.journal_info=NULL;
    zm_enter(); assert(!zm_app_allowed()); zm_exit(); assert(zm_app_allowed());
    task.flags=PF_KTHREAD; assert(!zm_app_allowed());
    task.flags=PF_EXITING; assert(!zm_app_allowed()); task.flags=0;
    task.mm=NULL; assert(!zm_app_allowed());
    return 0;
}
'''
        self.compile_run(s)

    def test_ioctl_permission_state_and_compat_dispatch(self):
        s = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <stddef.h>
typedef struct { unsigned int val; } kuid_t;
struct file { int unused; };
static unsigned int uid;
#define GLOBAL_ROOT_UID ((kuid_t){0})
static kuid_t current_euid(void) { return (kuid_t){uid}; }
static bool uid_eq(kuid_t a,kuid_t b) { return a.val==b.val; }
static bool admin;
#define CAP_SYS_ADMIN 21
static bool capable(int c) { return admin; }
static int zm_enabled, calls, waited;
#define atomic_read(p) (*(p))
#define atomic_set(p,v) (*(p)=(v))
static void synchronize_rcu(void) { waited++; }
static int zm_rule_change(unsigned long a,bool b) { calls++;return 0; }
static int zm_uid_change(unsigned long a,bool b) { calls++;return 0; }
static void zm_clear(void) { calls++; }
static int zm_list(unsigned long a) { calls++;return 0; }
#define __user
typedef uint32_t __u32;
#define compat_ptr(x) ((void *)(uintptr_t)(x))
'''
        s += HEADER[HEADER.index('#define ZEROMOUNT_VERSION'):HEADER.index('#ifdef CONFIG_ZEROMOUNT')]
        s += function(CORE, 'zm_ioctl_locked')
        s += '\nstatic long zeromount_ioctl(struct file *f,unsigned int c,unsigned long a) { return zm_ioctl_locked(c,a); }\n'
        s += function(CORE, 'zeromount_compat_ioctl')
        s += r'''
int main(void) {
    uid=10123; admin=true; assert(zm_ioctl_locked(ZEROMOUNT_IOC_ENABLE,0)==-EPERM);
    uid=0; admin=false; assert(zm_ioctl_locked(ZEROMOUNT_IOC_ENABLE,0)==-EPERM);
    admin=true; assert(zm_ioctl_locked(ZEROMOUNT_IOC_GET_STATUS,0)==0);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_GET_VERSION,0)==0x04190001);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_ENABLE,0)==0 && zm_enabled==1);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_ADD_RULE,0)==-EBUSY && calls==0);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_CLEAR_ALL,0)==-EBUSY);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_DISABLE,0)==0 && waited==1);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_ADD_RULE,0)==0 && calls==1);
    assert(zm_ioctl_locked(ZEROMOUNT_IOC_REFRESH,0)==-EOPNOTSUPP);
    assert(zm_ioctl_locked(_IO(0x33,1),0)==-ENOTTY);
    assert(sizeof(struct zeromount_compat_data)==12);
    assert(ZEROMOUNT_COMPAT_ADD!=ZEROMOUNT_IOC_ADD_RULE);
    assert(zeromount_compat_ioctl(NULL,ZEROMOUNT_COMPAT_ADD,0)==0 && calls==2);
    assert(zeromount_compat_ioctl(NULL,ZEROMOUNT_IOC_ADD_RULE,0)==-EINVAL);
    uid=10123; assert(zeromount_compat_ioctl(NULL,ZEROMOUNT_COMPAT_ADD,0)==-EPERM);
    return 0;
}
'''
        self.compile_run(s)

    def test_redirect_ownership_and_disabled_race(self):
        s = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
typedef unsigned int uid_t;
typedef unsigned int u32;
typedef struct { uid_t val; } kuid_t;
struct filename { const char *name; };
struct zm_rule { char *virtual_path; char *real_path; } rule_data;
struct zm_uid { uid_t uid; } blocked_data;
static struct filename original, replaced;
static bool allowed=true, has_rule, blocked, allocation_fail, filename_fail, disable_at_lock;
static int zm_enabled=1, depth, put_count, recursive;
#define atomic_read(p) (*(p))
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define IS_ERR_OR_NULL(p) (!(p) || (uintptr_t)(p)>=(uintptr_t)-4095)
#define GFP_ATOMIC 0
static bool zm_app_allowed(void) { return allowed; }
static kuid_t current_uid(void) { return (kuid_t){10123}; }
static u32 full_name_hash(void *salt,const char *p,size_t len) { return 0; }
static void rcu_read_lock(void) { depth++;if(disable_at_lock)zm_enabled=0; }
static void rcu_read_unlock(void) { assert(depth==1);depth--; }
static struct zm_rule *first_zm_rules(u32 h) { return has_rule ? &rule_data : NULL; }
static struct zm_uid *first_zm_blocked_uids(u32 h) { return blocked ? &blocked_data : NULL; }
#define hash_for_each_possible_rcu(table,obj,node,key) for(obj=first_##table(key);obj;obj=NULL)
static char *kstrdup(const char *s,int flags) { assert(depth==1);return allocation_fail?NULL:strdup(s); }
static void kfree(void *p) { free(p); }
static void putname(struct filename *p) { assert(p==&original);put_count++; }
static void zm_enter(void) { recursive++; }
static void zm_exit(void) { recursive--; }
static struct filename *getname_kernel(const char *p) {
    assert(depth==0 && recursive==1);
    assert(!strcmp(p,"/export/replacement"));
    return filename_fail ? ERR_PTR(-ENOMEM) : &replaced;
}
'''
        s += function(CORE, 'zm_valid_path') + '\n' + function(CORE, 'zeromount_getname_hook')
        s += r'''
int main(void) {
    original.name="/system/etc/test";
    rule_data.virtual_path="/system/etc/test"; rule_data.real_path="/export/replacement";
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    has_rule=true; blocked=true; blocked_data.uid=10123;
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    blocked=false; allowed=false;
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    allowed=true; disable_at_lock=true;
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    disable_at_lock=false; zm_enabled=1;
    assert(zeromount_getname_hook(&original)==&replaced && put_count==1);
    put_count=0;allocation_fail=true;
    assert(zeromount_getname_hook(&original)==ERR_PTR(-ENOMEM) && put_count==1);
    put_count=0;allocation_fail=false;filename_fail=true;
    assert(zeromount_getname_hook(&original)==ERR_PTR(-ENOMEM) && put_count==1);
    put_count=0;filename_fail=false;original.name="relative";
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    original.name="/system/etc/test/";
    assert(zeromount_getname_hook(&original)==&original && put_count==0);
    assert(depth==0 && recursive==0);
    return 0;
}
'''
        self.compile_run(s)


if __name__ == '__main__':
    unittest.main()
