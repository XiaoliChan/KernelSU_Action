#ifndef KSU_SUSFS_H
#define KSU_SUSFS_H

#include <linux/version.h>
#include <linux/types.h>
#include <linux/utsname.h>
#include <linux/hashtable.h>
#include <linux/path.h>
#include <linux/susfs_def.h>

#define SUSFS_VERSION "v1.5.9-v2compat"
#if LINUX_VERSION_CODE < KERNEL_VERSION(5,0,0)
#define SUSFS_VARIANT "NON-GKI"
#else
#define SUSFS_VARIANT "GKI"
#endif

/*********/
/* MACRO */
/*********/
#define getname_safe(name) (name == NULL ? ERR_PTR(-EINVAL) : getname(name))
#define putname_safe(name) (IS_ERR(name) ? NULL : putname(name))

/**********/
/* STRUCT */
/**********/
/* sus_path */
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
struct st_susfs_sus_path {
	unsigned long                    target_ino;
	char                             target_pathname[SUSFS_MAX_LEN_PATHNAME];
	unsigned int                     i_uid;
};

struct st_susfs_sus_path_list {
	struct list_head                 list;
	struct st_susfs_sus_path         info;
	char                             target_pathname[SUSFS_MAX_LEN_PATHNAME];
	size_t                           path_len;
};

struct st_android_data_path {
	char                             pathname[SUSFS_MAX_LEN_PATHNAME];
	bool                             is_inited;
};

struct st_sdcard_path {
	char                             pathname[SUSFS_MAX_LEN_PATHNAME];
	bool                             is_inited;
};
#endif

/* sus_mount */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
struct st_susfs_sus_mount {
	char                    target_pathname[SUSFS_MAX_LEN_PATHNAME];
	unsigned long           target_dev;
};

struct st_susfs_sus_mount_list {
	struct list_head                        list;
	struct st_susfs_sus_mount               info;
};
#endif

/* sus_kstat */
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
struct st_susfs_sus_kstat {
	int                     is_statically;
	unsigned long           target_ino; // the ino after bind mounted or overlayed
	char                    target_pathname[SUSFS_MAX_LEN_PATHNAME];
	unsigned long           spoofed_ino;
	unsigned long           spoofed_dev;
	unsigned int            spoofed_nlink;
	long long               spoofed_size;
	long                    spoofed_atime_tv_sec;
	long                    spoofed_mtime_tv_sec;
	long                    spoofed_ctime_tv_sec;
	long                    spoofed_atime_tv_nsec;
	long                    spoofed_mtime_tv_nsec;
	long                    spoofed_ctime_tv_nsec;
	unsigned long           spoofed_blksize;
	unsigned long long      spoofed_blocks;
};

struct st_susfs_sus_kstat_hlist {
	unsigned long                           target_ino;
	struct st_susfs_sus_kstat               info;
	struct hlist_node                       node;
};
#endif

/* try_umount */
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
struct st_susfs_try_umount {
	char                    target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int                     mnt_mode;
};

struct st_susfs_try_umount_list {
	struct list_head                        list;
	struct st_susfs_try_umount              info;
};
#endif

/* spoof_uname */
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
struct st_susfs_uname {
	char        release[__NEW_UTS_LEN+1];
	char        version[__NEW_UTS_LEN+1];
};
#endif

/* open_redirect */
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
struct st_susfs_open_redirect {
	unsigned long                    target_ino;
	char                             target_pathname[SUSFS_MAX_LEN_PATHNAME];
	char                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];
};

struct st_susfs_open_redirect_hlist {
	unsigned long                    target_ino;
	char                             target_pathname[SUSFS_MAX_LEN_PATHNAME];
	char                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];
	struct hlist_node                node;
};
#endif

/* sus_su */
#ifdef CONFIG_KSU_SUSFS_SUS_SU
struct st_sus_su {
	int         mode;
};
#endif

/***********************/
/* FORWARD DECLARATION */
/***********************/
/* sus_path */
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
int susfs_set_i_state_on_external_dir(char __user* user_info, int cmd);
void susfs_add_sus_path(void __user **user_info);
void susfs_add_sus_path_loop(void __user **user_info);
#endif
/* sus_mount */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
int susfs_add_sus_mount(struct st_susfs_sus_mount* __user user_info);
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
int susfs_auto_add_sus_bind_mount(const char *pathname, struct path *path_target);
#endif // #ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
void susfs_auto_add_sus_ksu_default_mount(const char __user *to_pathname);
#endif // #ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT

/* sus_kstat */
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
void susfs_add_sus_kstat(void __user **user_info);
void susfs_update_sus_kstat(void __user **user_info);
void susfs_sus_ino_for_generic_fillattr(unsigned long ino, struct kstat *stat);
void susfs_sus_ino_for_show_map_vma(unsigned long ino, dev_t *out_dev, unsigned long *out_ino);
#endif
/* try_umount */
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
int susfs_add_try_umount(struct st_susfs_try_umount* __user user_info);
void susfs_try_umount(uid_t target_uid);
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
void susfs_auto_add_try_umount_for_bind_mount(struct path *path);
#endif // #ifdef CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
#endif // #ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
/* spoof_uname */
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
void susfs_set_uname(void __user **user_info);
void susfs_spoof_uname(struct new_utsname* tmp);
#endif
/* set_log */
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
void susfs_set_log(bool enabled);
#endif
/* spoof_cmdline_or_bootconfig */
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
void susfs_set_cmdline_or_bootconfig(void __user **user_info);
int susfs_spoof_cmdline_or_bootconfig(struct seq_file *m);
#endif
/* open_redirect */
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
void susfs_add_open_redirect(void __user **user_info);
struct filename* susfs_get_redirected_path(unsigned long ino);
#endif
/* sus_su */
#ifdef CONFIG_KSU_SUSFS_SUS_SU
int susfs_get_sus_su_working_mode(void);
int susfs_sus_su(struct st_sus_su* __user user_info);
#endif

void susfs_get_enabled_features(void __user **user_info);

/* susfs_init */
void susfs_init(void);


/*************** v2 compatibility additions (fs/susfs_compat.c) ***************/

#ifndef SUSFS_ENABLED_FEATURES_SIZE
#define SUSFS_ENABLED_FEATURES_SIZE 8192
#endif
#ifndef SUSFS_VARIANT
#define SUSFS_VARIANT "NON-GKI-COMPAT"
#endif

/* v2-only user-facing structs */
struct st_susfs_hide_sus_mnts_for_non_su_procs {
	bool                                    enabled;
	int                                     err;
};
struct st_susfs_sus_map {
	char                                    target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int                                     err;
};
struct st_susfs_avc_log_spoofing {
	bool                                    enabled;
	int                                     err;
};
struct st_susfs_log {
	bool                                    enabled;
	int                                     err;
};
struct st_susfs_enabled_features {
	char                                    enabled_features[SUSFS_ENABLED_FEATURES_SIZE];
	int                                     err;
};
struct st_susfs_variant {
	char                                    susfs_variant[16];
	int                                     err;
};
struct st_susfs_version {
	char                                    susfs_version[16];
	int                                     err;
};

/* v2 entry points implemented by fs/susfs_compat.c */
void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info);
void susfs_add_sus_map(void __user **user_info);
void susfs_set_avc_log_spoofing(void __user **user_info);
void susfs_enable_log(void __user **user_info);
void susfs_get_enabled_features(void __user **user_info);
void susfs_show_variant(void __user **user_info);
void susfs_show_version(void __user **user_info);
void susfs_start_sdcard_monitor_fn(void);
void susfs_set_current_proc_umounted(void);
void susfs_set_current_proc_umounted_for_zygote_next(void);
void susfs_set_current_proc_no_su(void);
void susfs_clear_current_proc_no_su(void);
bool susfs_is_current_proc_umounted(void);
bool susfs_is_current_proc_no_su(void);
void susfs_set_sdcard_android_data_decrypted_key_false(void);

/* SukiSU-Ultra 'builtin' additions (fs/susfs_compat.c) */
bool susfs_starts_with(const char *str, const char *prefix);
bool susfs_ends_with(const char *str, const char *suffix);
int susfs_add_sus_type(const char *secctx, u32 type_value);
int susfs_add_sus_avd_allowed_by_type(u32 s_type, u32 t_type, u16 type, u32 orig_avd_allowed);
void susfs_set_priority_uid_filter(void __user **user_info);
void susfs_parse_priority_app_strings(void);

/* v1.5.9 implementations, renamed (see fs/susfs.c), consumed by susfs_compat.c */
int susfs_add_sus_path_kernel(const struct st_susfs_sus_path *request);
int susfs_add_sus_kstat_kernel(const struct st_susfs_sus_kstat *request);
int susfs_update_sus_kstat_kernel(const struct st_susfs_sus_kstat *request);
int susfs_add_open_redirect_kernel(const struct st_susfs_open_redirect *request);
int susfs_v159_add_sus_path(struct st_susfs_sus_path __user *user_info);
int susfs_v159_add_sus_kstat(struct st_susfs_sus_kstat __user *user_info);
int susfs_v159_update_sus_kstat(struct st_susfs_sus_kstat __user *user_info);
int susfs_v159_set_uname(struct st_susfs_uname __user *user_info);
int susfs_v159_set_cmdline_or_bootconfig(char __user *user_fake_boot_config);
int susfs_v159_add_open_redirect(struct st_susfs_open_redirect __user *user_info);
int susfs_v159_get_enabled_features(char __user *user_buf, size_t bufsize);

#endif
