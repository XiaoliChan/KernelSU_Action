# Super-Builders: useful ideas outside ZeroMount

Reviewed snapshot: `Enginex0/Super-Builders`
`c2cb71614868fe742cbffee2b6f3126523432673`. This is a source review, not a
claim that its kernels were built or booted on our 9R. Its README still lists
non-GKI 4.19 as planned. Our native SUSFS v2.4 port is not its 5.4 patch base.

## Priorities for this project

| Idea | Evidence in the source | Decision for our 4.19 baseline |
| --- | --- | --- |
| Separate upstream, local enhancements and fork-specific fixes | `50_`, `51_`, `70_` layering in each version directory | Adopt the separation and provenance discipline, not the entire patch stack |
| Pointer/error and string-boundary hardening | e.g. `d_path` error-pointer correction in `51_` | Our native v2 port already has `IS_ERR(dpath)` and uses `strscpy`; add regressions instead of duplicating older fixes |
| Flag-allocation and UID-boundary review | SUSFS/variant patch families and README safety checklist | Added tests for separate TIF/address-space flag namespaces and actual multi-user UID classification |
| Version/sublevel compatibility checks | `dry-test-patches.yml` matrix, reject collection and **full** compile | Useful before changing kernel/KSU pins; preserve our zero-fuzz and actual-config checks |
| Reuse downloaded build inputs | `cache-dependencies.yml` uploads inputs as artifacts for consumers | Worth adapting with immutable pins and digest checks; it is not a substitute for our existing ccache |
| Report effective feature states | `report-config.sh` reads the built `.config` | Keep our stricter expected-delta failure gate; optionally improve the human-readable summary |
| Critical-partition protection | `setup-bbg.sh` integrates Baseband-guard | Separate optional study; not a Bootloader hiding technique and not installed |

Source links:
- [5.4 patch architecture](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/android12-5.4/README.md)
- [5.4 local SUSFS enhancements](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/android12-5.4/SukiSU-Ultra/patches/51_enhanced_susfs-android12-5.4.patch)
- [Matrix and full-build validation](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/.github/workflows/dry-test-patches.yml)
- [Dependency download/distribution](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/.github/workflows/cache-dependencies.yml)

## Important differences: do not blindly transplant

1. The `70_` file inspected targets the older `kernel/supercalls.c` layout.
   Our pinned fork uses `kernel/supercall/dispatch.c` and different helper
   boundaries. A similarly named fix is not ABI-compatible evidence.
2. Our native v2 UID helper already uses `uid % 100000`, covering secondary-user
   apps. Do not replace it with a simple global UID threshold copied from an
   older port. Our old-kernel SID initialization fix also already exists.
3. The build workflow accepts some patch failures via `|| true` / fallback echo,
   and can continue after a nonzero build if any `Image` exists. We should retain
   fail-closed patch/config/build gates and output provenance instead.
4. Its `-F3` patch application is not our zero-fuzz contract. A matrix build
   passing is useful but does not justify silently accepting ambiguous hunks.
5. `bypass-abi-check.sh` and `clean-build-flags.sh` relax ABI checks and alter
   release suffixes. That is not suitable for the verified stock-module/loader
   compatibility assumptions of this 9R baseline.
6. Several external dependencies are obtained from moving branches or an online
   setup script. Reuse the artifact-distribution pattern only after pinning and
   recording the exact inputs; do not execute its setup scripts during review.
7. Compression, LTO and other performance selections need device measurements.
   No ZRAM, scheduler or compiler-policy change is made by this review.

Relevant source:
[build workflow](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/.github/workflows/build-sukisu.yml),
[ABI helper](https://github.com/Enginex0/Super-Builders/blob/c2cb71614868fe742cbffee2b6f3126523432673/android12-5.4/build-helpers/bypass-abi-check.sh).

## Baseband-guard is separate from BL concealment

[Baseband-guard](https://github.com/vc-teahouse/Baseband-guard) is an LSM for
restricting writes to selected critical partitions/device nodes. If considered
later, it needs a pinned-source review, 4.19 LSM compatibility checks, exact 9R
partition rules and OTA/recovery/root-maintenance tests. Do not add it casually:
an inappropriate write policy could also obstruct legitimate maintenance.

## Changes actually made in this research branch

- Added tests for TIF and address-space flag collisions/bounds, keeping their
  namespaces separate.
- Compiled the actual native v2 UID-classification helper against primary and
  secondary-user app/system UID cases.
- Added a regression preserving `IS_ERR(dpath)` in the current proc-fd hook.
- No Super-Builders kernel feature, Baseband-guard, performance change or
  ZeroMount implementation was enabled on the phone or merged into `main`.
