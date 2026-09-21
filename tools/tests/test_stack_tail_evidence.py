"""Final-link tail successors must not disappear from stack diagnostics."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stack_guard", ROOT / "tools/stack_usage_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class TailEvidenceTests(unittest.TestCase):
    def test_tail_successors_and_missing_library_are_reachable(self):
        text = """08006000 <main>:
 8006000: f000 f800 bl 8006010 <wrapper>
08006010 <wrapper>:
 8006010: f000 b800 b.w 8006020 <worker>
08006020 <worker>:
 8006020: f000 f800 bl 8006030 <library>
08006030 <library>:
 8006030: e7fe b.n 8006030 <library>
"""
        report = guard.analyze(text, dict(main=8, wrapper=16, worker=128))
        self.assertEqual(report["roots"]["main"]["known_frame_sum"], 152)
        self.assertEqual(report["call_edges"]["wrapper"], ["worker"])
        self.assertEqual(report["direct_edges"]["wrapper"], [])
        self.assertEqual(report["root_gaps"]["main"]["missing_frames"], ["library"])
        self.assertFalse(report["complete"])

    def test_conditional_offset_tail_keeps_uncertainty_and_follows_owner(self):
        text = """08006000 <main>:
 8006000: f040 8000 bne.w 8006014 <worker+0x4>
08006010 <worker>:
 8006010: f000 f800 bl 8006020 <leaf>
08006020 <leaf>:
 8006020: 4770 bx lr
"""
        report = guard.analyze(text, dict(main=8, worker=16, leaf=32))
        self.assertEqual(report["roots"]["main"]["known_frame_sum"], 56)
        self.assertEqual(report["tail_transfers"][0]["target"], "worker+0x4")
        self.assertTrue(report["root_gaps"]["main"]["tail_transfers"])
        self.assertFalse(report["complete"])

    def test_local_branch_is_not_a_tail_and_unrelated_irq_gap_is_separate(self):
        text = """08006000 <main>:
 8006000: e001 b.n 8006006 <main+0x6>
 8006006: 4770 bx lr
08006010 <UART4_IRQHandler>:
 8006010: 4798 blx r3
"""
        report = guard.analyze(text, dict(main=8, UART4_IRQHandler=16))
        self.assertEqual(report["tail_transfers"], [])
        self.assertEqual(report["root_gaps"]["main"]["indirect_transfers"], [])
        self.assertEqual(len(report["root_gaps"]["UART4_IRQHandler"]["indirect_transfers"]), 1)
        self.assertFalse(report["complete"])

    def test_tail_only_target_without_header_is_missing(self):
        report = guard.analyze("""08006000 <main>:
 8006000: f000 b800 b.w 8006010 <absent>
""", {"main": 8})
        self.assertIn("absent", report["missing_frames"])
        self.assertIn("absent", report["root_gaps"]["main"]["missing_frames"])

    def test_tail_cycle_terminates_and_stays_incomplete(self):
        report = guard.analyze("""08006000 <main>:
 8006000: f000 b800 b.w 8006010 <worker>
08006010 <worker>:
 8006010: f000 b800 b.w 8006000 <main>
""", dict(main=8, worker=16))
        self.assertTrue(report["cycles"])
        self.assertTrue(report["root_gaps"]["main"]["cycle_reachable"])
        self.assertFalse(report["complete"])


if __name__ == "__main__":
    unittest.main()
