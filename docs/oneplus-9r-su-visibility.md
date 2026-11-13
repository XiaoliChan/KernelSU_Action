# OnePlus 9R: SUSFS virtual-su visibility regression

## Finding (2026-11-13)

The native SUSFS v2.4 diagnostic profile combines the manual hooks in
`patches/oneplus-9r/minimal_hooks/kernel-4.19-sukisu.patch` with SukiSU commit
`1cfa57340590971cba7521ed536da8ebbedc5f0a`.

With `CONFIG_KSU_SUSFS=y`, the manual stat/access hooks called
`ksu_handle_stat()` / `ksu_handle_faccessat()` without checking the SU
compatibility switch, the task's no-su flag, or its root authorization. In
this pinned SukiSU version those handlers expect the caller to check policy
and rewrite `/system/bin/su` to `/system/bin/sh` themselves. The native SUSFS
upstream integration has these caller checks; the staged 4.19 manual port
omitted them.

Observed on the installed kernel:

- A standalone probe dropped its UID/EUID/GID to 65534, then successfully
  statted `/system/bin/su` with the same inode and size as `/system/bin/sh`.
- A successful root-shell directory listing contained `sh`, but not `su`.
  The probe's own directory listing was denied; that failure is **not**
  evidence of a missing entry.
- A separately inspected app checked root-manager packages and su-path
  existence in Application startup, then explicitly called `System.exit(0)`.
  Its real startup log and exit history confirmed a voluntary exit. This does
  not establish the reason for every other app's security warning.

The standalone probe retained its inherited SELinux context, so it is not an
exact reproduction of an Android app sandbox. It demonstrates the missing
UID boundary together with the patch/source analysis. Do not delete the
virtual `su` pathname or mistake its stat result for a physical system file.

## Fix

`susfs-v2/003-sucompat-visibility-guards.patch` adds a shared policy check to
the **handlers**, not just one manual-call site:

1. `READ_ONCE(ksu_su_compat_enabled)` must be true.
2. `susfs_is_current_proc_no_su()` must be false.
3. `__ksu_is_allow_uid_for_current(current_uid().val)` must authorize the task.

Only then may the existing filename/chroot checks and su-to-sh mapping run.
Denied calls leave the pathname unchanged and preserve normal VFS results;
they do not force arbitrary paths to ENOENT or grant root. The execve/init
path, non-SUSFS implementation, ADB-root, KPM and other SUSFS features are
unchanged.

`scripts/prepare-susfs-v2.sh` applies the patch with zero fuzz and includes it
in the existing diagnostic input hash manifest. The dedicated SUSFS workflow
has no release job; this is a candidate, not a replacement for verified releases.

## Verification

`tests/test_sucompat_visibility.py` compiles the actual before/after handler
code reconstructed from the patch with `-Wall -Werror` and UBSan:

- The pre-fix handlers must fail the policy matrix, proving the regression.
- The fixed handlers cover UID/grant combinations, feature enable/disable,
  no-su state, chroot, su/sh/unrelated paths and both stat/access handlers.
- Error pointers and NULL filename strings retain their original behavior.
- The test also verifies that the native v2 build applies the patch.

The patch applies to the pinned original source with zero fuzz. Host tests do
not prove device behavior: a kernel build and a temporary-boot comparison are
still required. On-device acceptance must verify denied-app path visibility,
authorized root operations, normal app startup and absence of new kernel
errors. No permanent flash or Play Integrity success is implied by this fix.
