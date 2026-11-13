#ifndef _LINUX_ZEROMOUNT_H
#define _LINUX_ZEROMOUNT_H
#include <linux/types.h>
#include <linux/fs.h>
#include <linux/sched.h>
#include <linux/thread_info.h>
#include <linux/ioctl.h>
/* Private experimental version: not advertised as full upstream module support. */
#define ZEROMOUNT_VERSION 0x04190001
#define ZEROMOUNT_MAGIC_CODE 0x5A
#define ZM_FLAG_ACTIVE 1U
struct zeromount_ioctl_data {
	char __user *virtual_path;
	char __user *real_path;
	unsigned int flags;
};
struct zeromount_compat_data { __u32 virtual_path; __u32 real_path; __u32 flags; };
#define ZEROMOUNT_IOC_ADD_RULE _IOW(ZEROMOUNT_MAGIC_CODE, 1, struct zeromount_ioctl_data)
#define ZEROMOUNT_IOC_DEL_RULE _IOW(ZEROMOUNT_MAGIC_CODE, 2, struct zeromount_ioctl_data)
#define ZEROMOUNT_IOC_CLEAR_ALL _IO(ZEROMOUNT_MAGIC_CODE, 3)
#define ZEROMOUNT_IOC_GET_VERSION _IOR(ZEROMOUNT_MAGIC_CODE, 4, int)
#define ZEROMOUNT_IOC_ADD_UID _IOW(ZEROMOUNT_MAGIC_CODE, 5, unsigned int)
#define ZEROMOUNT_IOC_DEL_UID _IOW(ZEROMOUNT_MAGIC_CODE, 6, unsigned int)
#define ZEROMOUNT_IOC_GET_LIST _IOR(ZEROMOUNT_MAGIC_CODE, 7, int)
#define ZEROMOUNT_IOC_ENABLE _IO(ZEROMOUNT_MAGIC_CODE, 8)
#define ZEROMOUNT_IOC_DISABLE _IO(ZEROMOUNT_MAGIC_CODE, 9)
#define ZEROMOUNT_IOC_REFRESH _IO(ZEROMOUNT_MAGIC_CODE, 10)
#define ZEROMOUNT_IOC_GET_STATUS _IOR(ZEROMOUNT_MAGIC_CODE, 11, int)
#define ZEROMOUNT_COMPAT_ADD _IOW(ZEROMOUNT_MAGIC_CODE, 1, struct zeromount_compat_data)
#define ZEROMOUNT_COMPAT_DEL _IOW(ZEROMOUNT_MAGIC_CODE, 2, struct zeromount_compat_data)
#ifdef CONFIG_ZEROMOUNT
#ifndef TIF_ZEROMOUNT
#error "ZeroMount requires the reviewed ARM64 recursion flag reservation"
#endif
static inline void zm_enter(void) { set_thread_flag(TIF_ZEROMOUNT); }
static inline void zm_exit(void) { clear_thread_flag(TIF_ZEROMOUNT); }
static inline bool zm_is_recursive(void) { return test_thread_flag(TIF_ZEROMOUNT); }
struct filename *zeromount_getname_hook(struct filename *name);
#else
static inline struct filename *zeromount_getname_hook(struct filename *name) { return name; }
#endif
#endif
