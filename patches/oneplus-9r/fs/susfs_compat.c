// SPDX-License-Identifier: GPL-2.0
/*
 * susfs v2 API compatibility layer on top of the frozen kernel-4.19
 * (v1.5.5) kernel-side implementation.
 *
 * Modern KernelSU forks (ReSukiSU / BakaSU / SukiSU-Ultra 'builtin') ship a
 * SUSFS glue layer that calls the v2-generation susfs API, while the last
 * non-GKI susfs branch is frozen at v1.5.5 and provides neither the v2
 * entry points nor the v2 user-facing struct layouts.
 *
 * This file provides the missing entry points. Struct layouts differ
 * between the generations, so the forwarding wrappers translate the v2
 * struct (sent by the manager) into the v1.5.5 layout, bounce it back into
 * the caller's user buffer, and hand it to the renamed v1.5.5
 * implementation (susfs_v159_*). All of this runs in the manager's own
 * syscall context, so the copy_to_user bounce is legal.
 *
 * Real implementations: sus_path / sus_kstat / spoof_uname / cmdline /
 * open_redirect forwarding, log toggle, enabled-features / variant /
 * version reporting, task umount/no-su tracking (v2-style thread flags),
 * deferred try-umount via susfs_extra_works.
 *
 * Accepted-but-inert stubs (v2-only features with no v1.5.5 consumer):
 * sus_map, sdcard monitor, avc log spoofing, hide-sus-mnts toggle -- v1.5.5
 * already spoofs sus mount ids unconditionally.
 */

#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/uaccess.h>
#include <linux/sched.h>
#include <linux/cred.h>
#include <linux/workqueue.h>
#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/string.h>
#include <linux/susfs.h>
#include <linux/susfs_def.h>

/* v2 user-facing layouts (manager side); only what the translations read. */
struct compat_v2_sus_path {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int err;
};

struct compat_v2_sus_kstat {
	bool is_statically;
	unsigned long target_ino;
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	unsigned long spoofed_ino;
	unsigned long spoofed_dev;
	unsigned int spoofed_nlink;
	long long spoofed_size;
	long spoofed_atime_tv_sec;
	unsigned long spoofed_atime_tv_nsec;
	long spoofed_mtime_tv_sec;
	unsigned long spoofed_mtime_tv_nsec;
	long spoofed_ctime_tv_sec;
	unsigned long spoofed_ctime_tv_nsec;
	long long spoofed_blocks;
	long spoofed_blksize;
	int flags;
	int err;
};

struct compat_v2_open_redirect {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	char redirected_pathname[SUSFS_MAX_LEN_PATHNAME];
	int uid_scheme;
	int err;
};

extern void susfs_set_log(bool enabled);
extern void susfs_try_umount(uid_t target_uid);

static void susfs_compat_remember_umount_uid(void);

/* ------------------------------------------------------------- sus_path */

static void compat_add_sus_path(void __user **user_info, bool is_loop)
{
	struct compat_v2_sus_path v2;
	struct st_susfs_sus_path v155;

	if (!user_info || !*user_info)
		return;
	if (copy_from_user(&v2, *user_info, sizeof(v2)))
		return;

	memset(&v155, 0, sizeof(v155));
	/* v1.5.9 keys by pathname (it resolves and marks the inodes itself);
	 * target_ino is informational, and i_uid is not part of the v2
	 * manager payload -- 0 keeps hiding unscoped. */
	strlcpy(v155.target_pathname, v2.target_pathname,
		sizeof(v155.target_pathname));
	v155.i_uid = 0;

	if (copy_to_user(*user_info, &v155, sizeof(v155)))
		return;
	susfs_v159_add_sus_path((struct st_susfs_sus_path __user *)*user_info);
}

void susfs_add_sus_path(void __user **user_info)
{
	compat_add_sus_path(user_info, false);
}

void susfs_add_sus_path_loop(void __user **user_info)
{
	/* v1.5.5 has no loop-mount distinction; hide it as a plain path. */
	compat_add_sus_path(user_info, true);
}

/* ------------------------------------------------------------ sus_kstat */

static void compat_fill_v155_kstat(struct st_susfs_sus_kstat *v155,
				   const struct compat_v2_sus_kstat *v2)
{
	memset(v155, 0, sizeof(*v155));
	v155->is_statically = v2->is_statically;
	v155->target_ino = v2->target_ino;
	strlcpy(v155->target_pathname, v2->target_pathname,
		sizeof(v155->target_pathname));
	v155->spoofed_ino = v2->spoofed_ino;
	v155->spoofed_dev = v2->spoofed_dev;
	v155->spoofed_nlink = v2->spoofed_nlink;
	v155->spoofed_size = v2->spoofed_size;
	/* field order differs between generations: v2 interleaves
	 * sec/nsec, v1.5.5 groups all secs then all nsecs */
	v155->spoofed_atime_tv_sec = v2->spoofed_atime_tv_sec;
	v155->spoofed_mtime_tv_sec = v2->spoofed_mtime_tv_sec;
	v155->spoofed_ctime_tv_sec = v2->spoofed_ctime_tv_sec;
	v155->spoofed_atime_tv_nsec = v2->spoofed_atime_tv_nsec;
	v155->spoofed_mtime_tv_nsec = v2->spoofed_mtime_tv_nsec;
	v155->spoofed_ctime_tv_nsec = v2->spoofed_ctime_tv_nsec;
	v155->spoofed_blksize = v2->spoofed_blksize;
	v155->spoofed_blocks = v2->spoofed_blocks;
}

static void compat_kstat_common(void __user **user_info, bool update)
{
	struct compat_v2_sus_kstat v2;
	struct st_susfs_sus_kstat v155;

	if (!user_info || !*user_info)
		return;
	if (copy_from_user(&v2, *user_info, sizeof(v2)))
		return;

	compat_fill_v155_kstat(&v155, &v2);
	if (copy_to_user(*user_info, &v155, sizeof(v155)))
		return;
	if (update)
		susfs_v159_update_sus_kstat(
			(struct st_susfs_sus_kstat __user *)*user_info);
	else
		susfs_v159_add_sus_kstat(
			(struct st_susfs_sus_kstat __user *)*user_info);
}

void susfs_add_sus_kstat(void __user **user_info)
{
	compat_kstat_common(user_info, false);
}

void susfs_update_sus_kstat(void __user **user_info)
{
	compat_kstat_common(user_info, true);
}

/* ---------------------------------------------------------- spoof_uname */

void susfs_set_uname(void __user **user_info)
{
	/* release[]/version[] sit at offset 0 in both generations */
	if (!user_info || !*user_info)
		return;
	susfs_v159_set_uname((struct st_susfs_uname __user *)*user_info);
}

/* ------------------------------------------------- spoof cmdline/bootcfg */

void susfs_set_cmdline_or_bootconfig(void __user **user_info)
{
	/* v1.5.5 takes the raw char buffer, which is offset 0 of the v2 struct */
	if (!user_info || !*user_info)
		return;
	susfs_v159_set_cmdline_or_bootconfig((char __user *)*user_info);
}

/* -------------------------------------------------------- open_redirect */

void susfs_add_open_redirect(void __user **user_info)
{
	struct compat_v2_open_redirect v2;
	struct st_susfs_open_redirect v155;
	struct path path;
	int err;

	if (!user_info || !*user_info)
		return;
	if (copy_from_user(&v2, *user_info, sizeof(v2)))
		return;

	memset(&v155, 0, sizeof(v155));
	/* v1.5.5 keys the hash by target_ino; resolve it from the pathname,
	 * like the v2 implementation does internally. */
	err = kern_path(v2.target_pathname, LOOKUP_FOLLOW, &path);
	if (err) {
		pr_warn("susfs_compat: open_redirect target not found: %s\n",
			v2.target_pathname);
		return;
	}
	v155.target_ino = path.dentry->d_inode->i_ino;
	path_put(&path);
	strlcpy(v155.target_pathname, v2.target_pathname,
		sizeof(v155.target_pathname));
	strlcpy(v155.redirected_pathname, v2.redirected_pathname,
		sizeof(v155.redirected_pathname));

	if (copy_to_user(*user_info, &v155, sizeof(v155)))
		return;
	susfs_v159_add_open_redirect(
		(struct st_susfs_open_redirect __user *)*user_info);
}

/* ------------------------------------------------------------ misc real */

void susfs_enable_log(void __user **user_info)
{
	struct st_susfs_log log;

	if (!user_info || !*user_info)
		return;
	if (copy_from_user(&log, *user_info, sizeof(log)))
		return;
	susfs_set_log(log.enabled);
}

void susfs_get_enabled_features(void __user **user_info)
{
	char buf[256];
	int len = 0;

	if (!user_info || !*user_info)
		return;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
	len += scnprintf(buf + len, sizeof(buf) - len, "sus_path sus_path_loop ");
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
	len += scnprintf(buf + len, sizeof(buf) - len, "sus_kstat ");
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
	len += scnprintf(buf + len, sizeof(buf) - len, "spoof_uname ");
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
	len += scnprintf(buf + len, sizeof(buf) - len, "spoof_cmdline_or_bootconfig ");
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
	len += scnprintf(buf + len, sizeof(buf) - len, "open_redirect ");
#endif
	scnprintf(buf + len, sizeof(buf) - len, "(%s)", SUSFS_VERSION);

	copy_to_user(*user_info, buf, strlen(buf) + 1);
	put_user(0, &((struct st_susfs_enabled_features __user *)*user_info)->err);
}

void susfs_show_variant(void __user **user_info)
{
	struct st_susfs_variant v;

	if (!user_info || !*user_info)
		return;
	memset(&v, 0, sizeof(v));
	strlcpy(v.susfs_variant, SUSFS_VARIANT, sizeof(v.susfs_variant));
	v.err = 0;
	copy_to_user(*user_info, &v, sizeof(v));
}

void susfs_show_version(void __user **user_info)
{
	struct st_susfs_version v;

	if (!user_info || !*user_info)
		return;
	memset(&v, 0, sizeof(v));
	strlcpy(v.susfs_version, SUSFS_VERSION, sizeof(v.susfs_version));
	v.err = 0;
	copy_to_user(*user_info, &v, sizeof(v));
}

/* ------------------------------------------------- task state (v2 TIFs) */

void susfs_set_current_proc_umounted(void)
{
#ifdef TIF_PROC_UMOUNTED
	set_thread_flag(TIF_PROC_UMOUNTED);
	susfs_compat_remember_umount_uid();
#endif
}

void susfs_set_current_proc_umounted_for_zygote_next(void)
{
#ifdef TIF_PROC_UMOUNTED_FOR_ZYGOTE_NEXT
	set_thread_flag(TIF_PROC_UMOUNTED_FOR_ZYGOTE_NEXT);
	susfs_compat_remember_umount_uid();
#endif
}

void susfs_set_current_proc_no_su(void)
{
#ifdef TIF_PROC_NO_SU
	set_thread_flag(TIF_PROC_NO_SU);
#endif
}

void susfs_clear_current_proc_no_su(void)
{
#ifdef TIF_PROC_NO_SU
	clear_thread_flag(TIF_PROC_NO_SU);
#endif
}

bool susfs_is_current_proc_umounted(void)
{
#ifdef TIF_PROC_UMOUNTED
	return test_thread_flag(TIF_PROC_UMOUNTED);
#else
	return false;
#endif
}

bool susfs_is_current_proc_no_su(void)
{
#ifdef TIF_PROC_NO_SU
	return test_thread_flag(TIF_PROC_NO_SU);
#else
	return false;
#endif
}

void susfs_set_sdcard_android_data_decrypted_key_false(void)
{
	/* v2 sdcard state tracking; no v1.5.5 consumer */
}

/* --------------------------------------------- deferred try-umount work */

static uid_t susfs_compat_umount_uid;
static atomic_t susfs_compat_umount_pending = ATOMIC_INIT(0);

static void susfs_compat_remember_umount_uid(void)
{
	WRITE_ONCE(susfs_compat_umount_uid, current_uid().val);
	atomic_set(&susfs_compat_umount_pending, 1);
}

/*
 * v2's susfs_extra_works walks a per-uid umount list; v1.5.5 only offers
 * susfs_try_umount(uid). Single-slot approximation: remember the uid whose
 * process last marked itself umounted and try-umount it when the work is
 * scheduled.
 */
static void susfs_extra_works_handler(struct work_struct *work)
{
	if (atomic_xchg(&susfs_compat_umount_pending, 0))
		susfs_try_umount(READ_ONCE(susfs_compat_umount_uid));
}

struct work_struct susfs_extra_works;

static int __init susfs_compat_init(void)
{
	INIT_WORK(&susfs_extra_works, susfs_extra_works_handler);
	return 0;
}
late_initcall(susfs_compat_init);

/* ------------------------------------------------------------- inert... */

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
	struct st_susfs_hide_sus_mnts_for_non_su_procs req;

	/* accepted but not stored: v1.5.5 spoofs sus mount ids
	 * unconditionally, which covers the common use of this toggle */
	if (user_info && *user_info)
		copy_from_user(&req, *user_info, sizeof(req));
}

void susfs_add_sus_map(void __user **user_info)
{
	/* v2 sus_map has no v1.5.5 consumer */
}

void susfs_set_avc_log_spoofing(void __user **user_info)
{
	struct st_susfs_avc_log_spoofing req;

	if (user_info && *user_info)
		copy_from_user(&req, *user_info, sizeof(req));
}

void susfs_start_sdcard_monitor_fn(void)
{
	/* v2 sdcard anti-detection monitor; inert on v1.5.5 */
}

/* ------------------------------------- SukiSU-Ultra 'builtin' additions */

/*
 * String helpers its adb_root feature relies on (real implementations --
 * they are plain suffix/prefix checks in v2 as well).
 */
bool susfs_starts_with(const char *str, const char *prefix)
{
	size_t n;

	if (!str || !prefix)
		return false;
	n = strlen(prefix);
	return strncmp(str, prefix, n) == 0;
}

bool susfs_ends_with(const char *str, const char *suffix)
{
	size_t ls, lf;

	if (!str || !suffix)
		return false;
	ls = strlen(str);
	lf = strlen(suffix);
	return ls >= lf && strcmp(str + ls - lf, suffix) == 0;
}

/*
 * v2 SELinux type/avd spoofing: called while the fork reloads sepolicy.
 * v1.5.9 has no matching kernel-side machinery; accept and stay inert so
 * policy loads proceed normally.
 */
int susfs_add_sus_type(const char *secctx, u32 type_value)
{
	return 0;
}

int susfs_add_sus_avd_allowed_by_type(u32 s_type, u32 t_type, u16 type,
				      u32 orig_avd_allowed)
{
	return 0;
}

/* v2 priority uid filter -- inert on v1.5.9 */
void susfs_set_priority_uid_filter(void __user **user_info)
{
}

void susfs_parse_priority_app_strings(void)
{
}
