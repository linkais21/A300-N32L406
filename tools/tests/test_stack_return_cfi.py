"""A stack-pop PC return needs instruction and final-ELF CFI agreement."""

from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class StackReturnCfiTests(unittest.TestCase):
    def test_final_elf_return_provenance(self):
        compiler = ROOT / ".toolchain/bin/arm-none-eabi-gcc.exe"
        objdump = ROOT / ".toolchain/bin/arm-none-eabi-objdump.exe"
        if not compiler.is_file() or not objdump.is_file():
            self.skipTest("ARM toolchain is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "returns.S"
            elf = root / "returns.elf"
            source.write_text(
                ".syntax unified\n.thumb\n.cfi_sections .debug_frame\n"
                ".global good\n.type good, %function\ngood:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "ldr.w pc, [sp], #4\n.cfi_endproc\n.size good, .-good\n"
                ".global bad\n.type bad, %function\nbad:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -8\n"
                "ldr.w pc, [sp], #4\n.cfi_endproc\n.size bad, .-bad\n"
                ".global table\n.type table, %function\ntable:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "ldr.w pc, [r1, r3, lsl #2]\n.cfi_endproc\n.size table, .-table\n",
                encoding="ascii",
            )
            result = subprocess.run([str(compiler), "-mcpu=cortex-m4", "-mthumb",
                                     "-g3", "-nostdlib", "-Wl,-e,good", str(source),
                                     "-o", str(elf)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            disassembly = subprocess.run([str(objdump), "-d", str(elf)],
                                         check=True, capture_output=True,
                                         text=True).stdout
            returns = guard.dwarf_return_evidence(elf, disassembly)
            self.assertEqual({item["caller"] for item in returns.values()}, {"good"})
            report = guard.analyze(disassembly, {"good": 4, "bad": 4, "table": 4}, returns)
            self.assertEqual({item["caller"] for item in report["indirect_transfers"]},
                             {"bad", "table"})

    def test_no_cfi_does_not_clear_pc_write(self):
        disassembly = """00001000 <main>:
 1000: f85d fb04  ldr.w pc, [sp], #4
"""
        report = guard.analyze(disassembly, {"main": 4})
        self.assertEqual(report["indirect_transfers"][0]["kind"], "pc_write")


if __name__ == "__main__":
    unittest.main()
