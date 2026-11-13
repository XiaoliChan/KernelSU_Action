# OnePlus 9R ZeroMount: staged experimental port

## Status and scope

This is **stage 1: the absolute-file redirection core**, not a completed port
of Super-Builders' full ZeroMount engine or its userspace module. Do not install
the upstream ZeroMount module on the assumption that every ioctl feature works.
The experimental version is deliberately `0x04190001`, rather than upstream `1`.

The stable, device-verified ADB-root + KPM + SUSFS kernel is unchanged. This
branch adds a separate config and a **diagnostic-only** workflow. Nothing is
flashed or published automatically. A successful build is not device acceptance.

Source reference: Enginex0/Super-Builders commit
`c2cb71614868fe742cbffee2b6f3126523432673`, Android 12 / 5.4 SukiSU patch `60_`.
Unmodified extracted sources live in `patches/oneplus-9r/zeromount/upstream/`;
their checksums and the source-patch hash are in
`config/reference/oneplus-9r-zeromount-lock.json`.

Target: LineageOS SM8250 commit `078365e5318de0a30a41f9707070b610bcd20f13`,
native SUSFS v2.4 foundation, with the sucompat authorization repair from
`6cc5eb8`. No Super-Builders kernel image, defconfig, boot identity, or blanket
permission bypass is imported.

## Stage 1 behavior

- `CONFIG_ZEROMOUNT` defaults to **n**. Only the experimental profile selects it.
- Runtime always starts **disabled**, with empty, nonpersistent rules.
- Root **and** `CAP_SYS_ADMIN` are required at device open and every ioctl,
  including calls through an FD passed to an unprivileged process.
- Existing, absolute, regular file paths can be redirected to other existing
  regular files. Both must be root-owned, world-readable and not group/other
  writable. Final symlinks, directories, new-file injection and unsupported
  rule flags are rejected.
- No `/system/foo` ↔ `/foo` aliasing, dot-segment normalization or trailing-slash
  rewriting. Relative path lookups are intentionally unchanged in this stage.
- Root-authorized tasks, system/shell UIDs (including secondary-user system
  UIDs), kernel/exiting tasks, filesystem transactions and SUSFS-unmounted tasks
  bypass redirection. A root-controlled UID exclusion list is also available.
- Ordinary DAC, filesystem and SELinux checks still apply to the destination.
  This may prevent access to a target under `/data/adb`; the port does **not**
  silently grant traversal/read access to fix it. This limitation must be
  resolved before claiming general Android-module loading compatibility.
- No readdir injection, d_path substitution, mmap/kstat/statfs spoofing or
  SELinux xattr spoofing is connected to VFS. No hardware-attestation changes.

## Differences from the referenced engine

The first-stage core is reduced instead of carrying unreachable, unvalidated
directory/metadata machinery into the kernel:

1. **Recursion:** reserve ARM64 thread flag 36 after verifying it does not
   collide with the pinned ARM64/SUSFS flags. Do not borrow `journal_info` or
   change `task_struct` layout. An existing filesystem transaction is skipped.
2. **Concurrency:** RCU protects read-side rule lifetime; a mutex serializes
   control operations. Rule/UID mutation while enabled returns `EBUSY`.
   Disable waits for an RCU grace period. Already-linearized operations can
   finish; no claim of a transactional filesystem-wide stop is made.
3. **No Bloom prefilter:** readers consult the authoritative RCU table, avoiding
   false-negative lookups during in-place bitmap rebuilding.
4. **32-bit ABI:** translate the 12-byte compat request to the native pointer
   representation and translate its ioctl numbers. Do not forward a 32-bit
   request to a handler expecting a 24-byte native structure.
5. **Failure handling:** preserve original names on misses/disabled policy;
   propagate allocation failure after a rule match, rather than silently reading
   the wrong original file. Filename ownership is transferred exactly once.
6. **Bounded control data:** at most 256 rules and 256 excluded UIDs; rule listing
   is bounded to 64 KiB. Duplicate rules/UIDs are rejected. Refresh and directory
   flags return unsupported instead of pretending to work.

## Build and verification

Workflow: `.github/workflows/build-oneplus-9r-sukisu-zeromount.yml`.
Profile: `config/oneplus-9r-lineage-sukisu-zeromount.env`.
Expected config delta over the verified SUSFS profile: **only
`CONFIG_ZEROMOUNT=y`**. The compiler, kernel, SukiSU and KPM pins stay unchanged.
The workflow compiles `fs/zeromount.o` and `fs/namei.o` first, then the full
kernel, and uploads diagnostic artifacts without a release job.

`tests/test_zeromount.py` compiles actual functions with `-Wall -Werror` and
UBSan to exercise path/file validation, root/UID policy, task recursion,
ioctl privilege/state/compat dispatch, filename ownership, allocation failure,
and a disable-versus-reader interleaving. It also checks source hashes and
isolation from stable workflows. These doubles are not an SMP or device test.

The integration patch was generated against the exact 4.19 files after the
existing manual hooks and native SUSFS port; it must apply with **zero fuzz**.

### Device acceptance (not yet performed)

`tests/zeromount_probe.go` is a standalone diagnostic, not an autostart module:

```sh
GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
  go build -trimpath -o /tmp/zm-probe tests/zeromount_probe.go
GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 \
  go build -trimpath -o /tmp/zm-probe-arm32 tests/zeromount_probe.go
```

After an explicitly authorized temporary boot of a validated candidate, run
the diagnostic as root with `smoke /data/local/tmp`. It refuses a different
ABI, active state or pre-existing rules. It creates only disposable files,
checks a dropped-UID worker, root exclusion, denied ioctl through an inherited
FD, disabled restoration and UID exclusion, then removes its own rules/files.
Do not disable SELinux or relax file permissions to force a test pass.

Before promotion: validate both ABIs, read/write/exec permissions, concurrent
lookups during disable/clear, no-op behavior with no rules, core root/KPM/SUSFS
functionality, and normal app operation. Only then decide the next slice:
relative-path consistency, virtual directory entries, virtual metadata and
module-loader integration. Each requires its own tests and explicit scope.
