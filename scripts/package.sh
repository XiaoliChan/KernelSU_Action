#!/usr/bin/env bash
# Package build output: AnyKernel3 flashable zip and, optionally, a boot image.

set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KERNEL_DIR=${KERNEL_DIR:?KERNEL_DIR must be set}
WORKSPACE=${WORKSPACE:-$(cd "${KERNEL_DIR}/.." && pwd)}
ARCH=${ARCH:-arm64}
BOOT_OUT="${KERNEL_DIR}/out/arch/${ARCH}/boot"
AK3="${WORKSPACE}/AnyKernel3"
PACKAGE_REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# Pin the tooling independently of the device-specific installation policy.
AK3_COMMIT=41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1

configure_anykernel3() {
	local device=${ANYKERNEL3_DEVICE:-} slot=${ANYKERNEL3_SLOT_DEVICE:-auto}
	[[ "$device" =~ ^[a-zA-Z0-9_-]*$ ]] || die "invalid ANYKERNEL3_DEVICE"
	case "$slot" in auto | 0 | 1) ;; *) die "invalid ANYKERNEL3_SLOT_DEVICE" ;; esac
	cp "${PACKAGE_REPO_ROOT}/packaging/anykernel.sh" "${AK3}/anykernel.sh"
	# Never ship upstream's example payloads (init.tuna, fstab, ramdisk files).
	rm -rf "${AK3}/patch" "${AK3}/ramdisk" "${AK3}/modules"
	sed -i "s/^IS_SLOT_DEVICE=auto;/IS_SLOT_DEVICE=${slot};/" "${AK3}/anykernel.sh"
	if [ -n "$device" ]; then
		sed -i "s/^do.devicecheck=0$/do.devicecheck=1/; s/^device.name1=$/device.name1=${device}/" "${AK3}/anykernel.sh"
	fi
}

make_anykernel3() {
	group "Building AnyKernel3 package"
	rm -rf "$AK3"

	if is_true "${USE_CUSTOM_ANYKERNEL3:-false}"; then
		local src=${CUSTOM_ANYKERNEL3_SOURCE:?CUSTOM_ANYKERNEL3_SOURCE required}
		case "$src" in
			*.tar.gz | *.tgz)
				fetch "$src" "${WORKSPACE}/ak3.tar.gz"
				extract_archive "${WORKSPACE}/ak3.tar.gz" "$AK3" ;;
			*.zip)
				fetch "$src" "${WORKSPACE}/ak3.zip"
				extract_archive "${WORKSPACE}/ak3.zip" "$AK3" ;;
			*git*)
				retry 3 git clone -q --depth=1 ${CUSTOM_ANYKERNEL3_BRANCH:+-b "$CUSTOM_ANYKERNEL3_BRANCH"} \
					"$src" "$AK3" || die "failed to clone ${src}" ;;
			*)
				fetch "$src" "${WORKSPACE}/ak3.zip"
				extract_archive "${WORKSPACE}/ak3.zip" "$AK3" ;;
		esac
	else
		git init -q "$AK3"
		git -C "$AK3" remote add origin https://github.com/osm0sis/AnyKernel3
		retry 3 git -C "$AK3" fetch -q --depth=1 origin "$AK3_COMMIT" \
			|| die "failed to fetch pinned AnyKernel3"
		git -C "$AK3" checkout -q --detach FETCH_HEAD
		configure_anykernel3
	fi

	cp "${BOOT_OUT}/${KERNEL_IMAGE_NAME}" "${AK3}/" \
		|| die "kernel image missing at ${BOOT_OUT}/${KERNEL_IMAGE_NAME}"
	if is_true "${CHECK_DTBO_IS_OK:-false}"; then
		cp "${BOOT_OUT}/dtbo.img" "${AK3}/"
	fi
	rm -rf "${AK3}/.git" "${AK3}/.github" "${AK3}/README.md"

	# Archive before upload-artifact: uploading a directory loses executable
	# modes on download. The inner zip preserves recovery tools and symlinks.
	[ -f "${AK3}/anykernel.sh" ] && [ -f "${AK3}/META-INF/com/google/android/update-binary" ] \
		|| die "AnyKernel3 is missing its flashing entry points"
	local archive="${WORKSPACE}/AnyKernel3${LOCALVERSION:-}${UPLOADNAME:-}-${DEVICE:-kernel}-${BUILD_TIME:-local}.zip"
	rm -f "$archive"
	( cd "$AK3" && zip -qry9 "$archive" . ) || die "failed to archive AnyKernel3"
	unzip -tq "$archive" >/dev/null || die "AnyKernel3 zip integrity check failed"
	if ! is_true "${USE_CUSTOM_ANYKERNEL3:-false}"; then
		python3 "${PACKAGE_REPO_ROOT}/scripts/verify-anykernel.py" "$archive" \
			--device "${ANYKERNEL3_DEVICE:-}" --slot "${ANYKERNEL3_SLOT_DEVICE:-auto}" \
			--image-name "$KERNEL_IMAGE_NAME" --image "${BOOT_OUT}/${KERNEL_IMAGE_NAME}" \
			|| die "AnyKernel3 installer audit failed"
	fi
	export_env ANYKERNEL3_ZIP "$archive"
	ok "AnyKernel3 flashable zip: ${archive}"
	endgroup
}

make_boot_image() {
	is_true "${BUILD_BOOT_IMG:-false}" || return 0
	group "Repacking boot image"

	local tools="${WORKSPACE}/tools"
	[ -x "${tools}/unpack_bootimg.py" ] || [ -f "${tools}/unpack_bootimg.py" ] \
		|| die "mkbootimg tools not found at ${tools}"

	fetch "${SOURCE_BOOT_IMAGE:?SOURCE_BOOT_IMAGE required}" "${WORKSPACE}/boot-source.img"

	cd "$WORKSPACE"
	local fmt
	fmt=$(python3 "${tools}/unpack_bootimg.py" --boot_img boot-source.img --format mkbootimg) \
		|| die "failed to read the source boot image"
	info "source boot image args: ${fmt}"

	python3 "${tools}/unpack_bootimg.py" --boot_img boot-source.img >/dev/null \
		|| die "failed to unpack the source boot image"

	cp "${BOOT_OUT}/${KERNEL_IMAGE_NAME}" "${WORKSPACE}/out/kernel" \
		|| die "could not stage the new kernel into the unpacked ramdisk"

	# shellcheck disable=SC2086
	eval "python3 \"${tools}/mkbootimg.py\" ${fmt} -o boot.img" \
		|| die "mkbootimg failed"
	[ -s "${WORKSPACE}/boot.img" ] || die "boot.img was not produced"

	ok "boot.img built ($(du -h "${WORKSPACE}/boot.img" | cut -f1))"
	export_env MAKE_BOOT_IMAGE_IS_OK true
	endgroup
}

write_summary() {
	summary ""
	summary "### Build artifacts"
	summary ""
	summary "| Artifact | Size |"
	summary "| --- | --- |"
	local f
	for f in "${BOOT_OUT}/${KERNEL_IMAGE_NAME}" "${BOOT_OUT}/dtbo.img" "${WORKSPACE}/boot.img"; do
		[ -f "$f" ] && summary "| \`$(basename "$f")\` | $(du -h "$f" | cut -f1) |"
	done
	[ -d "$AK3" ] && summary "| \`AnyKernel3\` (flashable zip) | $(du -sh "$AK3" | cut -f1) |"
	summary ""
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
	case "${1:-all}" in
		anykernel3) make_anykernel3 ;;
		bootimg)    make_boot_image ;;
		all)        make_anykernel3; make_boot_image; write_summary ;;
		*) die "unknown package step '$1'" ;;
	esac
fi
