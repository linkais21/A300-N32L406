"""Exercise the gate on real temporary BIN/MAP files; no target hardware needed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from map_ram_guard import flash_used


def app_map(size):
    return ("Memory Configuration\n"
            "FLASH 0x08006000 0x0001a000 xr\n"
            "Linker script and memory map\n"
            ".isr_vector 0x08006000 0x148\n"
            ".text 0x08006150 0x167ec\n"
            ".rodata 0x0801c93c 0x32b8\n"
            ".ARM 0x0801fbf8 0x8\n"
            ".init_array 0x0801fc00 0x4\n"
            ".fini_array 0x0801fc04 0x4\n"
            ".data 0x20000000 0x128 load address 0x0801fc08\n"
            f"  0x{0x08006000 + size:08x} _app_load_end = (LOADADDR (.data) + SIZEOF (.data))\n")


class FlashGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "app.bin"
        self.map = self.work / "app.map"
        self.elf = self.work / "app.elf"
        self.profile = self.work / "profile.json"
        self.baseline = self.work / "baseline.json"
        self.report = self.work / "report.json"
        self.elf.write_bytes(b"fixture ELF identity")
        configuration = {"compiler": "fixture GCC", "cflags": "-Os", "asflags": "-g0",
                         "ldflags": "-Os", "sdk_cflags": "", "signature_cflags": "-fno-lto",
                         "sources": "src/main.c"}
        self.profile.write_text(json.dumps({"schema_version": 1, "configuration": configuration,
            "elf_sha256": hashlib.sha256(self.elf.read_bytes()).hexdigest()}), encoding="utf-8")
        self.baseline.write_text(json.dumps({"schema_version": 1, "used_bytes": 105776,
            "origin": 0x08006000, "limit_bytes": 106496,
            "configuration": configuration}), encoding="utf-8")

    def check_gate(self, size=105776, map_text=None):
        self.bin.write_bytes(b"\xff" * size)
        self.map.write_text(app_map(size) if map_text is None else map_text, encoding="ascii")
        return subprocess.run([sys.executable, str(ROOT / "tools/flash_capacity_guard.py"),
            "check", "--bin", str(self.bin), "--map", str(self.map), "--elf", str(self.elf),
            "--profile", str(self.profile), "--baseline", str(self.baseline),
            "--output", str(self.report)], capture_output=True, text=True)

    def test_map_counts_data_load_and_alignment(self):
        self.assertEqual(flash_used(app_map(105776)), 105776)

    def test_low_headroom_and_baseline_delta(self):
        result = self.check_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(self.report.read_text())
        self.assertEqual((data["used_bytes"], data["remaining_bytes"], data["delta_bytes"]),
                         (105776, 720, 0))
        self.assertIn("LOW_HEADROOM", data["alerts"])
        self.assertIn("LOW_HEADROOM", result.stdout)
        self.assertEqual(data["bin_sha256"], hashlib.sha256(self.bin.read_bytes()).hexdigest())

    def test_boundaries(self):
        for size, code, low in [(102400, 0, False), (102401, 0, True),
                                (106496, 0, True), (106497, 1, True)]:
            with self.subTest(size=size):
                result = self.check_gate(size)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                data = json.loads(self.report.read_text())
                self.assertEqual("LOW_HEADROOM" in data["alerts"], low)
                self.assertEqual(data["delta_bytes"], size - 105776)

    def test_bad_inputs_fail_closed(self):
        for label, size, text in [
            ("truncated", 105775, app_map(105776)),
            ("empty bin", 0, app_map(0)),
            ("missing symbol", 105776, ".text 0x08006000 0x19d30\n"),
            ("wrong origin", 105776, app_map(105776).replace("FLASH 0x08006000", "FLASH 0x08000000")),
            ("wrong capacity", 105776, app_map(105776).replace("0x0001a000", "0x00020000")),
        ]:
            with self.subTest(label=label):
                result = self.check_gate(size, text)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("FAIL", result.stdout + result.stderr)

    def test_missing_file_fails_without_old_success_report(self):
        self.assertEqual(self.check_gate().returncode, 0)
        self.profile.unlink()
        self.assertEqual(self.check_gate().returncode, 1)
        self.assertEqual(json.loads(self.report.read_text())["status"], "failed")

    def test_configuration_drift_is_visible(self):
        profile = json.loads(self.profile.read_text())
        profile["configuration"]["cflags"] = "-O2"
        self.profile.write_text(json.dumps(profile))
        self.assertEqual(self.check_gate().returncode, 0)
        data = json.loads(self.report.read_text())
        self.assertIn("CONFIGURATION_CHANGED", data["alerts"])
        self.assertFalse(data["baseline_comparable"])

    def test_changed_elf_rejects_stale_profile(self):
        self.elf.write_bytes(b"different ELF")
        result = self.check_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ELF", result.stdout + result.stderr)

    def test_invalid_baseline_fails(self):
        for value in (True, -1, 106497):
            baseline = json.loads(self.baseline.read_text())
            baseline["used_bytes"] = value
            self.baseline.write_text(json.dumps(baseline))
            self.assertEqual(self.check_gate().returncode, 1)

    def test_missing_critical_flags_fail(self):
        original = json.loads(self.profile.read_text())
        for field in ("compiler", "cflags", "asflags", "ldflags", "signature_cflags", "sources"):
            for empty in ("", "   "):
                profile = json.loads(json.dumps(original))
                profile["configuration"][field] = empty
                self.profile.write_text(json.dumps(profile))
                with self.subTest(field=field, empty=empty):
                    self.assertEqual(self.check_gate().returncode, 1)

    def test_record_captures_configuration_and_elf_identity(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/flash_capacity_guard.py"),
            "record", "--compiler", sys.executable, "--elf", str(self.elf),
            "--output", str(self.profile), "--cflags=-Os -g0", "--asflags=-g0",
            "--ldflags=-Os -Wl,-Map=build/example/app.map", "--sdk-cflags=-Wno-unused-parameter",
            "--signature-cflags=-fno-lto", "--sources=src/main.c src/startup.s"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(self.profile.read_text())
        self.assertEqual(data["elf_sha256"], hashlib.sha256(self.elf.read_bytes()).hexdigest())
        self.assertEqual(data["configuration"]["ldflags"], "-Os -Wl,-Map=<output.map>")
        self.assertEqual(data["configuration"]["cflags"], "-Os -g0")
        self.assertEqual(data["configuration"]["signature_cflags"], "-fno-lto")
        self.assertTrue(data["configuration"]["compiler"].startswith("Python "))


if __name__ == "__main__":
    unittest.main()
