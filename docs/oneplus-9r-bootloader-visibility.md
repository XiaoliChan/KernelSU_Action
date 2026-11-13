# OnePlus 9R Bootloader visibility research (`dev`)

## Scope and current status

Research only. Base: `main` / `6cc5eb8`, the verified SU-path authorization fix.
ZeroMount remains paused on `dev-zeromount`; it is not part of this branch.
No bootloader lock/unlock command, partition write, property mutation,
attestation-key operation or application hook is performed by this work.

The initial offline pass had no connected ADB device. A follow-up read-only
collection on 2026-11-13 after the OTA/kernel restoration is recorded below.
The findings separate runtime observations from offline source inspection.
Nothing here establishes a new Play Integrity result or an app-level bypass.

## Previously observed facts

On 2026-11-13, the bootloader itself reported `unlocked: yes` before the
authorized temporary-boot test. A later Android shell reported:

| Property | Observed value |
| --- | --- |
| `ro.boot.verifiedbootstate` | `green` |
| `ro.boot.vbmeta.device_state` | `locked` |
| `ro.boot.flash.locked` | empty/unset |

Those are different observation channels, not contradictory proof about the
hardware. An empty property is **not** equivalent to `0` or `unlocked`. The
cause of the presented property values has not been established; do not
attribute them to SUSFS, microG or a module without checking runtime provenance.

The KernelSU pin `1cfa5734` is a kernel-only revision (top-level `kernel/` and
`uapi/`). It is not proof of which manager/userspace implementation is installed.

### Follow-up after the 2026-11-13 OTA

The allowlisted collector ran at **2026-11-13 13:28:23 UTC** through the home
host, against the updated system and restored stable kernel. Results:

| Interface | Verified-boot state | Other lock-related observation |
| --- | --- | --- |
| Android properties | `green` | `vbmeta.device_state=locked`; `flash.locked` empty/unset |
| `/proc/cmdline` | `orange` | No other allowlisted lock field observed |
| Device-tree chosen `bootargs` | `orange` | Same through the proc device-tree alias |
| `/proc/bootconfig` | unavailable | No inference of hidden or unlocked state |

This confirms a **local cross-interface inconsistency**, not just a possible
source gap. It does not identify the property writer or distinguish an unset
SUSFS replacement from a replacement that itself contains `orange`.

Collection context was ADB UID 0. `/proc/cmdline` was mode 0444, labeled
`proc_cmdline`; device-tree bootargs was mode 0444, labeled `sysfs`. DAC bits
alone do not establish access from an ordinary Android app's SELinux domain.
No app-sandbox read or hardware attestation was performed, and no values were
changed. Runtime SUSFS advertised the cmdline feature, but that capability flag
does not establish the contents of its active presentation buffer.

## Detection surfaces and evidence boundaries

| Surface | What to inspect | What it cannot prove |
| --- | --- | --- |
| Android properties | Selected `ro.boot.*` values; cached vs fresh reads; origin/timing | Genuine hardware lock state |
| `/proc/cmdline` | Selected `androidboot.*` fields, duplicates, permissions, active SUSFS presentation | Original loader input once substituted |
| `/proc/bootconfig` | Availability and fields, if implemented by the running kernel | Absence does not mean hidden or unlocked |
| Device-tree chosen `bootargs` | Availability, selected fields, **actual app readability** | Root-readable data is not necessarily app-readable |
| Hardware key attestation | Verified certificate chain, root-of-trust fields and challenge freshness | A changed property is not a changed signed proof |
| Play Integrity | Actual verdict for the requesting app/account/environment | A generic local “green” label is not a server verdict |

The [AOSP boot-flow specification](https://source.android.com/docs/security/features/verifiedboot/boot-flow)
distinguishes unlocked/ORANGE from locked states. [Key attestation](https://source.android.com/docs/security/features/keystore/attestation)
separately describes signed `deviceLocked` / `verifiedBootState` root-of-trust
fields. This research does not change those hardware-backed inputs.

## Current 4.19 SUSFS implementation

Pinned kernel source: `LineageOS/android_kernel_oneplus_sm8250`, commit
`078365e5318de0a30a41f9707070b610bcd20f13`.

1. `patches/oneplus-9r/susfs-v2/50_add_susfs_in_kernel-4.19.patch` hooks
   `cmdline_proc_show()` in `fs/proc/cmdline.c`.
2. A false-by-default static key selects the replacement. Until userspace
   supplies a buffer, the original `saved_command_line` path remains active.
3. The hooked path has **no per-UID predicate**: when enabled it presents the
   same replacement to every permitted reader, including root.
4. The setter in `susfs-v2/upstream/fs/susfs.c` rejects an empty buffer and
   enables the static key; this interface has no explicit disable operation.
   Restoring original text is not the same as disabling the feature. Any future
   experiment needs an explicit rollback design before changing this state.
5. The patch does not replace device-tree chosen `bootargs`. That is a possible
   cross-interface inconsistency, **not a confirmed app-visible leak**.
6. The pinned tree has `fs/proc/cmdline.c` but no `fs/proc/bootconfig.c`; the saved
   effective config has `CONFIG_CMDLINE_EXTEND=y` and the SUSFS cmdline option.
   The current device audit must still record availability rather than assuming
   that all kernels advertising 4.19 expose identical interfaces.

## Read-only collection

```sh
python3 scripts/audit-boot-visibility.py --serial YOUR_ADB_SERIAL \
  --output /tmp/boot-visibility-report.json
```

The collector uses only ADB `get-state`, `id -u`, selected `getprop` queries
and bounded `head` reads of the four listed proc/device-tree paths. It does
not run `adb root`, `su`, `resetprop`, `setprop`, fastboot, or any setter.

Reports contain an explicit shell-context label, not a claim of app-sandbox
visibility. Only allowlisted fields and enumerated values are retained; serials,
full command lines, raw error text and unknown values are discarded. Duplicate
fields are kept so conflicts are not silently resolved. Output is mode 0600
and refuses to overwrite an existing file. No device means a clear failure,
not a fabricated all-green report.

`tests/test_boot_visibility.py` covers redaction, duplicate keys, quoted/NUL
input, bootconfig syntax, missing values, read-only command selection and
private output. Matching local values always leave hardware state
`not_determined` and attestation `not_requested`.

## Next gates

1. Shell baseline collected after OTA; retain it for comparison without
   rebooting or altering values.
2. Determine the installed userspace/module version and where relevant
   property/cmdline settings come from. Do not read keyboxes or account data.
3. Establish what an ordinary app can actually read, using a separate minimal
   diagnostic client rather than inferring it from a root shell.
4. For any concrete app rejection, identify the decisive check before editing
   anything. Local file/property consistency and server/hardware attestation
   require separate conclusions.
5. If a local change is justified: one interface at a time, reversible state,
   unchanged unrelated boot arguments, no early-boot regression, and no broad
   “all apps pass” claim. No automatic relock on the current custom OS/kernel.
