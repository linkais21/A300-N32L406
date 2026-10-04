"""RAM-01 regressions use compiler/objdump-shaped fixtures, not firmware models."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import json

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def disassembly(edges):
    return "\n".join(f"{0x8006000+i*16:08x} <{name}>:\n" +
                     "\n".join(f" 8006000:\tf000 f800 \tbl\t8007000 <{target}>"
                               for target in targets)
                     for i, (name, targets) in enumerate(edges.items()))


class StackTests(unittest.TestCase):
    def test_app_ram_gate_rejects_absent_stack_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.map"
            path.write_text("FLASH 0x08006000 0x1a000 xr\n"
                            " 0x0801fd30 _app_load_end = LOADADDR (.data) + SIZEOF (.data)\n"
                            ".data 0x20000000 0x128\n.bss 0x20000128 0x4474\n")
            result = subprocess.run([sys.executable, str(ROOT / "tools/map_ram_guard.py"),
                                     "app", str(path)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("stack evidence", result.stdout)

    def test_ram_budget_shortfall_and_incomplete_bounds_both_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "app.map"
            path.write_text("FLASH 0x08006000 0x1a000 xr\n"
                            " 0x0801fd30 _app_load_end = LOADADDR (.data) + SIZEOF (.data)\n"
                            ".data 0x20000000 0x128\n.bss 0x20000128 0x4474\n")
            elf = root / "app.elf"
            manifest = root / "stack-evidence.json"
            elf.write_bytes(b"fixture")
            manifest.write_text("{}")
            for known, message in ((2984, "breaches required runtime gap"),
                                   (100, "incomplete stack evidence")):
                (root / "stack-analysis.json").write_text(json.dumps({
                    "map_sha256": guard.digest(path), "elf_sha256": guard.digest(elf),
                    "evidence_sha256": guard.digest(manifest), "known_main_frame_sum": known,
                    "status": "incomplete", "error": "unverified IRQ/heap"}))
                result = subprocess.run([sys.executable, str(ROOT / "tools/map_ram_guard.py"),
                                         "app", str(path)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stdout)

    def test_ota_lto_chain_includes_ecc_children(self):
        frames = dict(main=792, fota_process=1208, firmware_signature_verify=24,
                      uECC_verify=544, ecc_child=128)
        names = list(frames)
        edges = {name: names[i+1:i+2] for i, name in enumerate(names)}
        result = guard.analyze(disassembly(edges), frames)
        self.assertEqual(result["roots"]["main"]["known_frame_sum"], 2696)
        self.assertEqual(result["roots"]["main"]["path"], names)

    def test_missing_library_and_indirect_are_not_complete(self):
        text = disassembly({"main": ["library"], "library": []})
        text += "\n 8007000:\t4798      \tblx\tr3\n"
        result = guard.analyze(text, {"main": 792})
        self.assertIn("library", result["missing_frames"])
        self.assertTrue(result["indirect_transfers"])
        self.assertFalse(result["complete"])

    def test_tail_transfer_and_cycle_are_explicit(self):
        text = disassembly({"main": ["child"], "child": ["main"]})
        text += "\n 8007000:\tf000 b800 \tb.w\t8006000 <other>\n"
        result = guard.analyze(text, {"main": 8, "child": 16})
        self.assertTrue(result["cycles"])
        self.assertTrue(result["tail_transfers"])

    def test_duplicate_frames_use_maximum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.su"
            path.write_text("a.c:1:1:same\t80\tstatic\na.c:2:1:same\t8\tstatic\n")
            self.assertEqual(guard.load([path])["same"], 80)

    def test_dynamic_or_malformed_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.su"
            for line in ("a.c:1:1:foo\t8\tdynamic\n", "broken\n", "a.c:1:1:foo\t-1\tstatic\n"):
                path.write_text(line)
                with self.assertRaises(ValueError):
                    guard.load([path])

    def test_record_requires_final_lto_and_binds_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            elf = root / "app.elf"
            map_path = root / "app.map"
            su = root / "app.elf.ltrans0.ltrans.su"
            elf.write_bytes(b"ELF")
            map_path.write_text("MAP")
            su.write_text("a.c:1:1:main\t792\tstatic\n")
            manifest = root / "stack-evidence.json"
            guard.record(elf, map_path, [su], manifest)
            guard.verify_evidence(elf, map_path, manifest)
            for changed in (elf, map_path):
                old = changed.read_bytes()
                changed.write_bytes(old + b"changed")
                with self.assertRaises(ValueError):
                    guard.verify_evidence(elf, map_path, manifest)
                changed.write_bytes(old)
            su.write_text("a.c:1:1:main\t8\tstatic\n")
            with self.assertRaises(ValueError):
                guard.verify_evidence(elf, map_path, manifest)
            with self.assertRaises(ValueError):
                guard.record(elf, map_path, [], manifest)

    def test_lto_private_names_match_but_other_clones_do_not(self):
        result = guard.analyze(disassembly({"main": ["helper.lto_priv.0", "helper.constprop.0"],
                                           "helper.lto_priv.0": []}), {"main": 8, "helper": 24})
        self.assertEqual(result["frames"]["helper.lto_priv.0"], 24)
        self.assertIn("helper.constprop.0", result["missing_frames"])

    def test_gcc_numberless_clone_report_is_used_without_borrowing_base_frame(self):
        result = guard.analyze(disassembly({"main": ["f39_execute.constprop.0"],
                                           "f39_execute.constprop.0": []}),
                               {"main": 792, "f39_execute": 8, "f39_execute.constprop": 1168})
        self.assertEqual(result["roots"]["main"]["known_frame_sum"], 1960)

    def test_missing_inputs_replace_earlier_success_even_in_report_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "stack-analysis.json"
            output.write_text('{"status":"passed"}')
            result = guard.check(root / "app.elf", root / "app.map", root / "evidence.json",
                                 root / "objdump", output, report_only=True)
            self.assertNotEqual(result, 0)
            self.assertIn('"status": "failed"', output.read_text())


if __name__ == "__main__":
    unittest.main()
