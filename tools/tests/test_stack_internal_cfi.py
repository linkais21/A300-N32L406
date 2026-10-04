"""Local BL may share one CFI frame only without reentry or nested calls."""

from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class InternalCfiTests(unittest.TestCase):
    def test_shared_frame_and_recursive_rejection(self):
        compiler = ROOT / ".toolchain/bin/arm-none-eabi-gcc.exe"
        objdump = ROOT / ".toolchain/bin/arm-none-eabi-objdump.exe"
        if not compiler.is_file() or not objdump.is_file():
            self.skipTest("ARM toolchain is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "internal.S"
            elf = root / "internal.elf"
            source.write_text(
                ".syntax unified\n.thumb\n.cfi_sections .debug_frame\n"
                ".global good\n.type good, %function\ngood:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "bl good+8\npop {pc}\nbx lr\n"
                ".cfi_endproc\n.size good, .-good\n"
                ".global bad\n.type bad, %function\nbad:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "bl bad+8\npop {pc}\nb bad+2\n"
                ".cfi_endproc\n.size bad, .-bad\n"
                ".global indirect\n.type indirect, %function\nindirect:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "bl indirect+8\npop {pc}\nbx r3\n"
                ".cfi_endproc\n.size indirect, .-indirect\n"
                ".global gap_loop\n.type gap_loop, %function\ngap_loop:\n.cfi_startproc\n"
                "push {lr}\n.cfi_def_cfa_offset 4\n.cfi_offset lr, -4\n"
                "bl gap_loop+12\nb gap_loop+2\nnop\nnop\nb gap_loop+6\n"
                ".cfi_endproc\n.size gap_loop, .-gap_loop\n",
                encoding="ascii",
            )
            result = subprocess.run([str(compiler), "-mcpu=cortex-m4", "-mthumb",
                                     "-g3", "-nostdlib", "-Wl,-e,good", str(source),
                                     "-o", str(elf)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            disassembly = subprocess.run([str(objdump), "-d", str(elf)],
                                         check=True, capture_output=True,
                                         text=True).stdout
            proofs = guard.dwarf_internal_call_evidence(elf, disassembly)
            self.assertEqual({item["caller"] for item in proofs.values()}, {"good"})
            report = guard.analyze(disassembly, {"good": 4, "bad": 4,
                                                 "indirect": 4, "gap_loop": 4},
                                   proven_internal_calls=proofs)
            self.assertEqual([item["caller"] for item in
                              report["unresolved_internal_calls"]],
                             ["bad", "indirect", "gap_loop"])


if __name__ == "__main__":
    unittest.main()
