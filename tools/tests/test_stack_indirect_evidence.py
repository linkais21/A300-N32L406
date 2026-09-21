"""Unresolved Thumb table branches must never yield complete stack evidence."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class IndirectEvidenceTests(unittest.TestCase):
    def test_table_branch_alone_blocks_complete(self):
        for op, operands in (("tbb", "[pc, r3]"), ("tbh", "[pc, r3, lsl #1]"),
                             ("tbb", "[r0, r1]")):
            with self.subTest(op=op, operands=operands):
                dis = f"08006000 <main>:\n 8006000: e8df f003 {op} {operands}\n"
                result = guard.analyze(dis, {"main": 8})
                self.assertFalse(result["complete"])
                self.assertEqual(len(result["indirect_transfers"]), 1)
                self.assertEqual(result["indirect_transfers"][0]["kind"], "table_branch")
                self.assertEqual(result["root_gaps"]["main"]["indirect_transfers"],
                                 result["indirect_transfers"])

    def test_irq_table_is_reported_only_for_reachable_roots(self):
        dis = """08006000 <main>:
 8006000: 4770 bx lr
08006010 <UART4_IRQHandler>:
 8006010: f000 f800 bl 8006020 <dispatch>
08006020 <dispatch>:
 8006020: e8df f013 tbh [pc, r3, lsl #1]
"""
        result = guard.analyze(dis, {"main": 8, "UART4_IRQHandler": 16, "dispatch": 24})
        self.assertFalse(result["complete"])
        self.assertFalse(result["root_gaps"]["main"]["indirect_transfers"])
        self.assertEqual(len(result["root_gaps"]["UART4_IRQHandler"]["indirect_transfers"]), 1)

    def test_classification_never_removes_unproven_returns_or_callbacks(self):
        dis = """08006000 <main>:
 8006000: 4798 blx r3
 8006002: 4718 bx r3
 8006004: f85d fb04 ldr.w pc, [sp], #4
 8006008: e8df f003 tbb [pc, r3]
"""
        result = guard.analyze(dis, {"main": 8})
        self.assertEqual([t["kind"] for t in result["indirect_transfers"]],
                         ["register_call", "register_branch", "pc_write", "table_branch"])
        self.assertFalse(result["complete"])

    def test_similar_nonbranch_mnemonics_and_table_data_are_not_branches(self):
        dis = """08006000 <main>:
 8006000: b2c9 uxtbhi r1, r1
 8006002: 4770 bx lr
 8006004: 00000100 .word 0x00000100
"""
        result = guard.analyze(dis, {"main": 8})
        self.assertFalse(result["indirect_transfers"])
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
