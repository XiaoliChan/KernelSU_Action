# Native SUSFS v2.4.0 / OnePlus 9R 4.19 port

`upstream/` is byte-identical to simonpunk/susfs4ksu, branch
`gki-android12-5.10`, commit `5436438b5cc77f146e04f71070da153dabe17a9d`.
The source hashes and unchanged kernel/compiler/Suki/KPM pins are in
`config/reference/oneplus-9r-susfs-v2-lock.json`.

This is **not** the old 1.5.9 backend relabelled as v2. There is no
`susfs_compat.c`, no extra mount-ID allocator, and no `susfs_mnt_id_backup`
rewrite. Allocated IDs stay owned by the original IDA; borrowed KSU unshare
IDs are tagged and never released by the borrower.

Initial diagnostic stage enables native mount handling, uname, cmdline and
logging, always alongside ADB-root + KPM. Path/kstat/open-redirect/map and
priority-UID filtering remain explicitly disabled until their separate VFS
port is complete; this stage is **not full-feature/device validated**.
The full current upstream core and headers are retained unchanged, with a
separate 4.19 fsnotify callback adapter preserving deferred SRCU cleanup.

The mount port preserves 4.19 fs-pin initialization. Borrowed ownership is
tagged at allocation (also protecting early clone error paths), and a new
owning clone clears the inherited borrow flag. These cases require executable
lifecycle tests, not merely an assertion that a ZIP or manager page exists.

KernelSU's tested manual frontend and 4.19 SID initialization are retained.
New upstream 5.10-only SELinux-hide layout hooks are not blindly applied to
4.19. AVC log presentation is wired at 4.19's `avc_dump_query`, without
changing access decisions.

No automatic Release or permanent flashing. The user's daily kernel stays
on the verified no-SUSFS ADB-root + KPM build until explicit test approval.
