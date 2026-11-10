# OnePlus 9R working kernel reference

`oneplus-9r-lineage-24.config` was extracted from the IKCONFIG section of a
device-confirmed bootable LineageOS 24 kernel, not generated from the failing
KernelSU build. It contains build configuration only, no ramdisk or device data.

- Source boot SHA256: `55336ea90b712a542e94cd253cf9d1a57d61c6558646c87a04cb2328c96e191c`
- Source kernel SHA256: `1897e24802ddac286556e316026e55d1d47e1829896c36e77a4a8ea534143eca`
- Config SHA256: `f3a54b3a28fa78aab76c24ecc435ab56be5b6cf58cdb31c1ebcb5c8642ba32ba`
- Kernel source commit: `078365e5318de0a30a41f9707070b610bcd20f13`
- Compiler: Android Clang `r596125`, version `22.0.2`
- Exact compiler build: `15071444`, AOSP prebuilt commit
  [`9b144befdfd93b90e02c663504fb9f4b95f9faf8`](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+/9b144befdfd93b90e02c663504fb9f4b95f9faf8)

The moving `main-kernel/clang-r596125` directory now contains Android build
15682573. The first control attempt caught this banner difference and stopped
before compilation. The profile now fetches the immutable 15071444 snapshot;
the comparator still checks the full compiler identity without an ignore rule.

The stock-control workflow checks this file's hash, creates a new untracked
defconfig in a clean, pinned kernel tree, then compares every effective Kconfig
value before and after compilation. It never installs KernelSU, applies the
SUSFS/hide/manual-hook patches, or creates a Release.
