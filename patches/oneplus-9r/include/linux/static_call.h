/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Stub for kernels older than 5.10, where <linux/static_call.h> does not
 * exist. SukiSU-Ultra 'builtin' includes it unconditionally via
 * kernel_includes.h but never uses the static_call API on this tree, so
 * an empty header is sufficient (and guarded to be a no-op elsewhere).
 */
#ifndef _LINUX_STATIC_CALL_STUB_H
#define _LINUX_STATIC_CALL_STUB_H
#endif /* _LINUX_STATIC_CALL_STUB_H */
