"""Final-link table targets are evidence, not a dominance/whole-stack proof."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


TBB = """08006000 <main>:
 8006000: 2b01 cmp r3, #1
 8006002: d803 bhi.n 800600c <main+0xc>
 8006004: e8df f003 tbb [pc, r3]
 8006008: 0302 .short 0x0302
 800600a: bf00 nop
 800600c: 4770 bx lr
0800600e <child>:
 800600e: 4798 blx r3
 8006010: 4770 bx lr
"""


class TableTargetTests(unittest.TestCase):
    def test_decoded_cross_function_target_propagates_gaps_and_frames(self):
        result = guard.analyze(TBB, {"main": 8, "child": 32})
        table = result["table_target_evidence"][0]
        self.assertEqual(table["status"], "decoded_local_guard")
        self.assertEqual(table["table_hex"], "0203")
        self.assertEqual([t["address"] for t in table["targets"]], [0x800600c, 0x800600e])
        self.assertEqual([t["function"] for t in table["targets"]], ["main", "child"])
        self.assertEqual(result["call_edges"]["main"], ["child"])
        self.assertEqual(result["direct_edges"]["main"], [])
        self.assertEqual(result["roots"]["main"]["known_frame_sum"], 40)
        self.assertEqual(len(result["root_gaps"]["main"]["indirect_transfers"]), 2)
        self.assertFalse(result["complete"])
        missing = guard.analyze(TBB, {"main": 8})
        self.assertIn("child", missing["root_gaps"]["main"]["missing_frames"])

    def test_tbh_pc_is_instruction_plus_four_without_word_alignment(self):
        dis = """08006000 <main>:
 8006000: bf00 nop
 8006002: 2b02 cmp r3, #2
 8006004: d805 bhi.n 8006012 <main+0x12>
 8006006: e8df f013 tbh [pc, r3, lsl #1]
 800600a: 0003 .short 0x0003
 800600c: 00040003 .word 0x00040003
 8006010: bf00 nop
 8006012: 4770 bx lr
"""
        result = guard.analyze(dis, {"main": 8})
        table = result["table_target_evidence"][0]
        self.assertEqual([t["address"] for t in table["targets"]],
                         [0x8006010, 0x8006010, 0x8006012])
        self.assertEqual(result["call_edges"]["main"], [])
        self.assertFalse(result["complete"])

    def test_unproven_or_malformed_tables_never_gain_targets(self):
        variants = [
            TBB.replace("[pc, r3]", "[r0, r3]"),
            TBB.replace("cmp r3", "cmp r2"),
            TBB.replace("bhi.n", "bhs.n"),
            TBB.replace("#1", "#65536"),
            TBB.replace("800600c <main+0xc>", "8006090 <main+0x90>"),
            TBB.replace(" 8006008: 0302 .short 0x0302\n", ""),
            TBB.replace("0302 .short 0x0302", "03 .byte 0x03"),
            TBB.replace("0302 .short 0x0302", "302 .byte 0x302"),
            TBB.replace("0302 .short 0x0302", "0300 .short 0x0300"),
            TBB.replace("0302 .short 0x0302", "ff02 .short 0xff02"),
            TBB.replace(" 800600c: 4770 bx lr", " 800600a: f04f 0000 mov.w r0, #0"),
            TBB.replace("8006002:", "8006001:"),
        ]
        for dis in variants:
            with self.subTest(dis=dis):
                result = guard.analyze(dis, {"main": 8, "child": 32})
                table = result["table_target_evidence"][0]
                self.assertEqual(table["status"], "unresolved")
                self.assertTrue(table["reason"])
                self.assertNotIn("targets", table)
                self.assertFalse(result["complete"])

    def test_direct_entry_bypassing_compare_is_visible_and_unresolved(self):
        dis = TBB + """08006020 <entry>:
 8006020: f7ff bff0 b.w 8006004 <main+0x4>
"""
        result = guard.analyze(dis, {"main": 8, "child": 32, "entry": 8})
        table = result["table_target_evidence"][0]
        self.assertEqual(table["bypass_entries"], [0x8006020])
        self.assertTrue(table["unresolved_obligations"])
        self.assertEqual(len(result["indirect_transfers"]), 2)
        self.assertFalse(result["complete"])

    def test_changed_table_bytes_change_targets_without_removing_unknowns(self):
        dis = TBB.replace("0302 .short 0x0302", "0202 .short 0x0202")
        result = guard.analyze(dis, {"main": 8, "child": 32})
        self.assertEqual([t["function"] for t in result["table_target_evidence"][0]["targets"]],
                         ["main", "main"])
        self.assertEqual(result["call_edges"]["main"], [])
        self.assertEqual(len(result["indirect_transfers"]), 2)
        self.assertFalse(result["complete"])

    def test_cbz_bypass_detected_but_literal_address_annotation_is_not_entry(self):
        dis = TBB + """08006020 <entry>:
 8006020: b100 cbz r0, 8006002 <main+0x2>
 8006022: 4800 ldr r0, [pc, #0] @ (8006004 <main+0x4>)
"""
        result = guard.analyze(dis, {"main": 8, "child": 32, "entry": 8})
        self.assertEqual(result["table_target_evidence"][0]["bypass_entries"], [0x8006020])


if __name__ == "__main__":
    unittest.main()
