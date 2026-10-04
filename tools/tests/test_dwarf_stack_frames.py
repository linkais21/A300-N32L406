"""Check that final ELF CFI supplies bounded frames, not guessed prologues."""

from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class DwarfFrameTests(unittest.TestCase):
    def test_rejects_non_stack_cfa_and_unbounded_offsets(self):
        self.assertEqual(guard.cfi_stack_bytes([(13, 0), (13, 24), (13, 8)]), 24)
        for rows in ([], [(11, 8)], [(13, -4)], [(13, None)]):
            with self.subTest(rows=rows):
                self.assertIsNone(guard.cfi_stack_bytes(rows))

    def test_final_elf_covers_compiler_and_library_frames(self):
        elf = ROOT / "build-stack-dwarf-trial-v3079/a300_firmware.elf"
        if not elf.is_file():
            self.skipTest("isolated ARM fixture build is unavailable")
        frames = guard.dwarf_frame_evidence(elf)
        self.assertEqual(frames["main"]["frame_bytes"], 416)
        self.assertEqual(frames["memcpy"]["frame_bytes"], 8)
        self.assertEqual(frames["gpio_af_rx"]["frame_bytes"], 24)
        self.assertGreaterEqual(frames["_svfiprintf_r"]["frame_bytes"], 144)

    def test_zero_size_library_symbol_uses_exact_fde(self):
        elf = ROOT / "build-ram-gate-pruned-v3079/a300_firmware.elf"
        if not elf.is_file():
            self.skipTest("isolated ARM fixture build is unavailable")
        frames = guard.dwarf_frame_evidence(elf)
        self.assertEqual(frames["memchr"]["frame_bytes"], 16)

    def test_generated_arm_elf_frame_and_symbol_coverage(self):
        compiler = ROOT / ".toolchain/bin/arm-none-eabi-gcc.exe"
        if not compiler.is_file():
            self.skipTest("ARM compiler is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.S"
            elf = root / "sample.elf"
            source.write_text(".syntax unified\n.thumb\n.cfi_sections .debug_frame\n"
                              ".global leaf\n.type leaf, %function\nleaf:\n"
                              ".cfi_startproc\n"
                              "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                              "sub sp, #40\n.cfi_def_cfa_offset 44\n"
                              "add sp, #40\n.cfi_def_cfa_offset 4\n"
                              "pop {pc}\n.cfi_endproc\n.size leaf, .-leaf\n",
                              encoding="ascii")
            result = subprocess.run([str(compiler), "-mcpu=cortex-m4", "-mthumb",
                                     "-g3", "-nostdlib", "-Wl,-e,leaf", str(source),
                                     "-o", str(elf)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            frames = guard.dwarf_frame_evidence(elf)
            self.assertIn("leaf", frames, frames)
            self.assertEqual(frames["leaf"]["frame_bytes"], 44)

    def test_zero_size_entry_does_not_credit_interior_symbol(self):
        compiler = ROOT / ".toolchain/bin/arm-none-eabi-gcc.exe"
        if not compiler.is_file():
            self.skipTest("ARM compiler is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.S"
            elf = root / "sample.elf"
            source.write_text(".syntax unified\n.thumb\n.cfi_sections .debug_frame\n"
                              ".global entry\n.type entry, %function\nentry:\n"
                              ".cfi_startproc\n"
                              "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                              ".global interior\n.type interior, %function\ninterior:\n"
                              "nop\npop {pc}\n.cfi_endproc\n"
                              ".global plain\n.type plain, %function\nplain:\n"
                              ".cfi_startproc\n"
                              "push {r4, lr}\n.cfi_def_cfa_offset 8\n"
                              "sub sp, #4\n.cfi_def_cfa_offset 12\n"
                              "add sp, #4\n.cfi_def_cfa_offset 8\n"
                              "pop {r4, pc}\n.cfi_endproc\n",
                              encoding="ascii")
            result = subprocess.run([str(compiler), "-mcpu=cortex-m4", "-mthumb",
                                     "-g3", "-nostdlib", "-Wl,-e,entry", str(source),
                                     "-o", str(elf)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            frames = guard.dwarf_frame_evidence(elf)
            self.assertNotIn("entry", frames)
            self.assertNotIn("interior", frames)
            self.assertEqual(frames["plain"]["frame_bytes"], 12)


if __name__ == "__main__":
    unittest.main()
