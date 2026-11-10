### KernelSU Action: kernel-only AnyKernel3 installer
# The packager fills the device/slot policy below. No example ramdisk edits.
properties() { '
kernel.string=KernelSU Action
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=boot;
IS_SLOT_DEVICE=auto;
SLOT_SELECT=active;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;
NO_VBMETA_PARTITION_PATCH=1;

. tools/ak3-core.sh;

# Keep the existing ramdisk intact; replace only the kernel in boot.
# This deliberately preserves any existing Magisk installation.
split_boot;
flash_boot;
# A no-op unless the build explicitly supplied dtbo.img.
flash_generic dtbo;
