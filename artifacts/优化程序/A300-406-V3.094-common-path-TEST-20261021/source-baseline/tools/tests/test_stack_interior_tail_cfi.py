"""Interior direct branches need a bounded final-ELF owner frame."""

from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class InteriorTailCfiTests(unittest.TestCase):
    def test_final_elf_cfi_proves_only_code_inside_bounded_owner(self):
        compiler = ROOT / ".toolchain/bin/arm-none-eabi-gcc.exe"
        objdump = ROOT / ".toolchain/bin/arm-none-eabi-objdump.exe"
        if not compiler.is_file() or not objdump.is_file():
            self.skipTest("ARM toolchain is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tails.S"
            elf = root / "tails.elf"
            source.write_text(
                ".syntax unified\n.thumb\n.cfi_sections .debug_frame\n"
                ".global caller\n.type caller, %function\ncaller:\n"
                "b target+2\n.size caller, .-caller\n"
                ".global target\n.type target, %function\ntarget:\n.cfi_startproc\n"
                "nop\npush {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "pop {pc}\n.cfi_endproc\n.size target, .-target\n"
                ".global bad_caller\n.type bad_caller, %function\nbad_caller:\n"
                "b unbounded+2\n.size bad_caller, .-bad_caller\n"
                ".global unbounded\n.type unbounded, %function\nunbounded:\n"
                "nop\npush {lr}\npop {pc}\n.size unbounded, .-unbounded\n",
                encoding="ascii",
            )
            result = subprocess.run([str(compiler), "-mcpu=cortex-m4", "-mthumb",
                                     "-g3", "-nostdlib", "-Wl,-e,caller", str(source),
                                     "-o", str(elf)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            disassembly = subprocess.run([str(objdump), "-d", str(elf)],
                                         check=True, capture_output=True,
                                         text=True).stdout
            frames = guard.dwarf_frame_evidence(elf)
            proofs = guard.dwarf_interior_tail_evidence(disassembly, frames)
            self.assertEqual({item["owner"] for item in proofs.values()}, {"target"})
            report = guard.analyze(disassembly,
                                   {"caller": 8, "target": 4,
                                    "bad_caller": 8, "unbounded": 4},
                                   proven_interior_tails=proofs)
            self.assertEqual(report["roots"]["caller"]["known_frame_sum"], 12)
            self.assertEqual([item["caller"] for item in
                              report["unresolved_tail_transfers"]], ["bad_caller"])


if __name__ == "__main__":
    unittest.main()
