"""No-device tests for the hash-locked Nova rescue builder."""
import gzip
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "nova_rescue", ROOT / "scripts/build-oneplus9r-nova-rescue.py")
rescue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rescue)


class NovaRescueTests(unittest.TestCase):
    def setUp(self):
        self.kernel = b"prefix\0ksu.force_feature\0" + rescue.RC + b"\0suffix"

    def test_comments_exactly_four_commands_and_preserves_logd(self):
        result = rescue.patch_kernel(self.kernel)
        self.assertEqual(len(result), len(self.kernel))
        self.assertEqual(sum(x != y for x, y in zip(result, self.kernel)), 4)
        self.assertEqual(result.count(b"    #xec u:r:ksu:s0"), 4)
        self.assertIn(b"    start logd\n", result)
        self.assertNotIn(rescue.EXEC, result)

    def test_refuses_unknown_or_duplicate_rc_and_separate_preinit(self):
        for image in (
            self.kernel.replace(b"post-fs-data", b"unknown"),
            self.kernel + rescue.RC + b"\0",
            self.kernel + b"ksu.preinit\0",
            self.kernel.replace(b"ksu.force_feature\0", b""),
        ):
            with self.subTest(image=image[:16]), self.assertRaises(ValueError):
                rescue.patch_kernel(image)

    def test_boot_v2_sections_and_split_command_line(self):
        buf = bytearray(6 * 4096)
        buf[:8] = b"ANDROID!"
        for offset, value in ((8, 3), (16, 4), (36, 4096), (40, 2), (1648, 3)):
            struct.pack_into("<I", buf, offset, value)
        buf[64:576] = b"a" * 512
        buf[608:610] = b" z"
        buf[4096:4099] = b"img"
        buf[8192:8196] = b"rdsk"
        buf[12288:12291] = b"dtb"
        with patch.object(rescue, "BOOT_SIZE", len(buf)):
            self.assertEqual(rescue.boot_sections(bytes(buf)),
                             (b"img", b"rdsk", b"dtb", b"a" * 512 + b" z"))
            struct.pack_into("<I", buf, 1648, 0xFFFFFFFF)
            with self.assertRaisesRegex(ValueError, "invalid section lengths"):
                rescue.boot_sections(bytes(buf))

    def test_no_output_for_wrong_input_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            source, packer, out = d / "raw.img.gz", d / "magiskboot", d / "nova-rescue.img"
            source.write_bytes(gzip.compress(b"wrong backup"))
            packer.write_bytes(b"fixture")
            with patch.object(rescue, "PACKER_SHA", rescue.sha(b"fixture")):
                with self.assertRaisesRegex(ValueError, "not the verified Nova boot"):
                    rescue.build(source, packer, None, out)
            self.assertFalse(out.exists())
            out.write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "output already exists"):
                rescue.build(source, packer, None, out)
            self.assertEqual(out.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
