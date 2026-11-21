# OnePlus 9R: temporary Nova boot-loop rescue

This is the **temporary** rescue image that booted on the 9R after switching from
standalone NyaZygisk to Nova's built-in Zygisk caused a boot loop. It is not a ROM,
normal kernel build or recovery installer. **Never flash it or include it in a release.**

- Base: [9R run 44863989700](https://github.com/XiaoliChan/KernelSU_Action/actions/runs/44863989700),
  Nova `builtin` `4bec532`, LineageOS 24.0-20261120, boot v2.
- Original full Nova boot SHA-256: `3af7c8d8d3968857381220efff343f1099f5391f0b491cb56036cc8cac44779d`.
- Rescue full boot SHA-256: `7ed1851c4bcf93b0df6e21c387a0faedbd45d655dd5a37e5cb634ba9a1f9ff64`.

The builder comments out four automatic `ksud` invocations in the known kernel
init fragment, preserving the ramdisk and DTB byte for byte. It requests the
existing ADB-root feature on this boot only. It does not grant new ADB keys,
make SELinux permissive or persist a change to any module, slot or partition.
The stock image and normal Nova image are unchanged. This is not the built-in
safe mode, which can persist disabled markers for ordinary modules.

## Reproduce the tested image

Use the **matching normal Nova boot_a backup**, not stock boot, a different OTA,
or the raw Image from a release. The builder refuses other hashes and never
communicates with a phone. Keep all actual boot images outside Git.

```sh
unzip -p "$ANYKERNEL_ZIP" tools/magiskboot > /tmp/9r-magiskboot
chmod 700 /tmp/9r-magiskboot
python3 scripts/build-oneplus9r-nova-rescue.py \
  --base-boot /path/to/boot_a-nova-candidate.img.gz \
  --magiskboot /tmp/9r-magiskboot \
  --runner /usr/bin/qemu-arm-static \
  --output /tmp/boot_a-nova-rescue-20261121.img
```

Omit `--runner` on a host that executes the ARM packer natively. The fixed packer
comes from the original AnyKernel3 artifact. The output must reproduce the
exact rescue SHA-256 above.

## Verified recovery sequence

1. Check the device is the 9R, its active slot and ROM match the backed-up
   build, and the original boot partition has been backed up. Use
   `fastboot boot /tmp/boot_a-nova-rescue-20261121.img`, **never `fastboot flash`**.
2. Wait for Android startup, then confirm ADB UID 0 and that `/data` is actually
   mounted. Do not attempt to mount raw encrypted userdata in Recovery.
3. Disable only Built-in Zygisk in Nova. If the UI cannot do it, its persistent
   enable flag is `/data/adb/ksu/.builtin_zygisk`; a reversible rename of this
   single flag is enough. Leave unrelated modules and account data alone.
4. Reboot normally. Verify that the original Nova boot hash is unchanged and
   that the rescue-only command-line argument is absent.

The rescue boot reached Android and decrypted/mounted `/data` with root ADB.
The operator then manually disabled the built-in provider and re-enabled the
standalone NyaZygisk module. Normal boot, the original Nova boot partition hash,
ADB-root, KPM ABI 2 and SUSFS v2.4.0 were confirmed afterward.

## Why the standalone provider can behave differently

The standalone module on this phone reported **NyaZygisk v2.5**,
`364-131e5f3-release`. Nova v3.0.0 instead pins
[BuiltZygisk `dfe0b4d`](https://github.com/SukiSU-Nova/BuiltZygisk/commit/dfe0b4d2cac3d91a72880b073c3f1d95bc8953d4),
a SukiSU integration merged with a different NyaZygisk upstream revision. The
engines share ancestry but are not the same build or integration.

The standalone provider is launched through its own module scripts. Nova
[stages its own binaries and starts the monitor](https://github.com/SukiSU-Nova/SukiSU-Nova/blob/v3.0.0/userspace/ksud/src/builtin_zygisk.rs)
in `ksud` before the ordinary module `post-fs-data` scripts, then has additional
[monitor/arming checks](https://github.com/SukiSU-Nova/SukiSU-Nova/blob/v3.0.0/userspace/ksud/src/init_event.rs)
at services and boot completion. A transition on a running system also uses a
separate provider handover path. Startup order or integration compatibility can
therefore differ even with the same family of loader.

Observed: the normal Nova image failed with the built-in provider configured;
the rescue image skipped all automatic `ksud` stages and booted; the **same
normal Nova image** then booted with built-in off and standalone on. This
isolates the failing **provider configuration** on this phone, not a specific
crash mechanism. There was no pstore record in Recovery, and no failed-boot
trace has been confirmed. Do not assert a specific race, SELinux denial or
double injection without logs. For further diagnosis, inspect the rotated
Nova boot logs under `/data/adb/ksu/log/` without reproducing the boot loop
on the daily-use device.
