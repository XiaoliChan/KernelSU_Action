# Temporary unprivileged boot-visibility probe

Self-targeted instrumentation, no requested permissions, no exported UI,
no root request, no network or attestation operation. The runner refuses an
execution context below an app UID or outside `untrusted_app*`. It returns
only selected boot-state enum values and read-error categories, not raw
bootargs, device identifiers or exception messages.

## Build

Use a Linux JDK plus official Android platform/build-tools archives. The tested
build used platform 35 r02 and build-tools 35.0.0; target SDK is explicitly 37.
Only long-established Android APIs are used. The official repository manifest
checksums used to verify the archives were:

| Archive | SHA-1 (official repository manifest) |
| --- | --- |
| `platform-35_r02.zip` | `0bb560a90a7a2cbd0dd8348224d518b638fe7949` |
| `build-tools_r35_linux.zip` | `2cfaa0bbb2336e9ec18ed3ecea84fa2e2af607bc` |

From the repository root, set `ANDROID_JAR`, `BUILD_TOOLS` and an external
private `OUT` directory, all as absolute paths. Do not commit APKs, signing keys
or raw run logs.

```sh
mkdir -p "$OUT/classes" "$OUT/dex"
chmod 700 "$OUT"
javac --release 8 -cp "$ANDROID_JAR" -d "$OUT/classes" \
  tests/boot_visibility_app/src/org/kernelstudy/bootvisibilityprobe/Probe.java
java -cp "$BUILD_TOOLS/lib/d8.jar" com.android.tools.r8.D8 \
  --min-api 26 --lib "$ANDROID_JAR" --output "$OUT/dex" \
  "$OUT/classes/org/kernelstudy/bootvisibilityprobe/Probe.class"
"$BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" \
  --manifest tests/boot_visibility_app/AndroidManifest.xml \
  --min-sdk-version 26 --target-sdk-version 37 -o "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip "$OUT/unsigned.apk" classes.dex)
"$BUILD_TOOLS/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
```

Sign `aligned.apk` with a dedicated temporary **test APK** signing key using
apksigner (v2+), not any system or hardware-attestation key. Verify the resulting
APK signature and inspect its permissions before installing. This repository
contains no signing key or prebuilt binary.

## Run and remove

Installation needs explicit operator approval. Refuse to overwrite a preexisting
package with the same name. Install without `-g`, so no permission grants are
requested. Use a cleanup trap/finally block to uninstall even if the test fails.

```sh
adb install -t --no-streaming /path/to/signed-probe.apk
adb shell am instrument -w -r org.kernelstudy.bootvisibilityprobe/.Probe
adb uninstall org.kernelstudy.bootvisibilityprobe
adb shell pm path org.kernelstudy.bootvisibilityprobe
```

The final `pm path` must have no installed package path. Never enable SELinux
permissive mode or grant the probe root to make reads succeed. A failed read is
part of the result. The tested APK was removed after collection.

On the 9R's Android 17 system, the probe ran as UID 10130 in `untrusted_app`,
target SDK 37, with zero requested permissions. Properties showed green/locked;
cmdline and both device-tree bootargs paths returned permission denied. See the
[research record](../../docs/oneplus-9r-bootloader-visibility.md) for limits.
