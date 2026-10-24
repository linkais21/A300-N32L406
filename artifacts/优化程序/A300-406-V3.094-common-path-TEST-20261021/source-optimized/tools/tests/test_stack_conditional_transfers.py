"""R8 regressions: real Thumb transfers plus mnemonic classification boundaries."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('guard', ROOT / 'tools/stack_usage_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
TC = ROOT / '.toolchain/bin'


def assemble(body, worker='sub sp, #128\n add sp, #128\n bx lr'):
    with tempfile.TemporaryDirectory(prefix='stack_conditional_') as directory:
        path = Path(directory)
        source = '.syntax unified\n.thumb\n.text\n.global main\n.type main,%function\nmain:\n'
        source += body + '\n.size main,.-main\n.type worker,%function\nworker:\n'
        source += worker + '\n.size worker,.-worker\n'
        (path / 'fixture.s').write_text(source, encoding='ascii')
        subprocess.run([str(TC / 'arm-none-eabi-gcc.exe'), '-mcpu=cortex-m4', '-mthumb',
                        '-nostdlib', '-Wl,-Ttext=0x08006000,-e,main', str(path / 'fixture.s'),
                        '-o', str(path / 'fixture.elf')], check=True, capture_output=True, timeout=30)
        return subprocess.run([str(TC / 'arm-none-eabi-objdump.exe'), '-d', str(path / 'fixture.elf')],
                              check=True, capture_output=True, text=True, timeout=30).stdout


class ConditionalTransfers(unittest.TestCase):
    def test_real_conditional_direct_call_retains_frame_and_missing_successor(self):
        dis = assemble('push {r4,lr}\n cmp r0,#0\n it eq\n bleq worker\n pop {r4,pc}')
        self.assertIn('bleq', dis)
        report = guard.analyze(dis, {'main': 8, 'worker': 128})
        self.assertEqual(report['direct_edges']['main'], ['worker'])
        self.assertEqual(report['roots']['main']['known_frame_sum'], 136)
        self.assertTrue(report['complete'])
        report = guard.analyze(dis, {'main': 8})
        self.assertIn('worker', report['root_gaps']['main']['missing_frames'])
        self.assertFalse(report['complete'])

    def test_real_conditional_register_transfers_remain_unknown(self):
        for op, kind in [('blxeq', 'register_call'), ('bxeq', 'register_branch')]:
            with self.subTest(op=op):
                dis = assemble(f'push {{r4,lr}}\n cmp r0,#0\n it eq\n {op} r3\n pop {{r4,pc}}')
                report = guard.analyze(dis, {'main': 8, 'worker': 128})
                self.assertEqual(report['root_gaps']['main']['indirect_transfers'][0]['kind'], kind)
                self.assertFalse(report['complete'])

    def test_real_compare_branches_follow_cross_function_successors(self):
        for op in ('cbz', 'cbnz'):
            with self.subTest(op=op):
                dis = assemble(f'{op} r0,worker\n bx lr', 'sub sp,#128\n blx r3\n add sp,#128\n bx lr')
                report = guard.analyze(dis, {'main': 0, 'worker': 128})
                self.assertEqual(report['call_edges']['main'], ['worker'])
                self.assertEqual(report['roots']['main']['known_frame_sum'], 128)
                self.assertEqual(report['tail_transfers'], [{'caller': 'main', 'target': 'worker'}])
                self.assertTrue(report['root_gaps']['main']['indirect_transfers'])
                self.assertFalse(report['complete'])
                missing = guard.analyze(dis, {'main': 0})
                self.assertIn('worker', missing['root_gaps']['main']['missing_frames'])

    def test_local_compare_branches_and_ble_are_not_calls(self):
        dis = assemble('cbz r0,1f\n cbnz r1,1f\n cmp r0,#0\n ble 1f\n1: bx lr')
        report = guard.analyze(dis, {'main': 0, 'worker': 128})
        self.assertEqual(report['call_edges']['main'], [])
        self.assertEqual(report['tail_transfers'], [])
        self.assertTrue(report['complete'])
        dis = assemble('cmp r0,#0\n ble worker\n bx lr')
        report = guard.analyze(dis, {'main': 0, 'worker': 128})
        self.assertEqual(report['direct_edges']['main'], [])
        self.assertEqual(report['tail_transfers'], [{'caller': 'main', 'target': 'worker'}])

    def test_internal_call_is_not_proven_by_owner_frame(self):
        for call in ('bl', 'bleq'):
            pre = 'cmp r0,#0\n it eq\n' if call == 'bleq' else ''
            dis = assemble('push {r4,lr}\n' + pre + call + ' worker+2\n pop {r4,pc}',
                           'nop\n blx r3\n bx lr')
            report = guard.analyze(dis, {'main': 8, 'worker': 16})
            self.assertIn('worker', report['call_edges']['main'])
            self.assertEqual(report['root_gaps']['main']['internal_calls'][0]['target'], 'worker+0x2')
            self.assertTrue(report['root_gaps']['main']['indirect_transfers'])
            self.assertFalse(report['complete'])
        dis = assemble('push {r4,lr}\n cmp r0,#0\n it eq\n bleq 1f\n pop {r4,pc}\n1: bx lr')
        report = guard.analyze(dis, {'main': 8, 'worker': 128})
        self.assertTrue(report['root_gaps']['main']['internal_calls'])
        self.assertFalse(report['complete'])

    def test_compare_internal_target_retains_tail_gap(self):
        dis = assemble('cbz r0,worker+2\n bx lr', 'nop\n blx r3\n bx lr')
        report = guard.analyze(dis, {'main': 0, 'worker': 128})
        self.assertEqual(report['tail_transfers'][0]['target'], 'worker+0x2')
        self.assertTrue(report['root_gaps']['main']['indirect_transfers'])
        self.assertFalse(report['complete'])

    def test_condition_and_width_spellings(self):
        # Classifier boundaries beyond the few mnemonics emitted by the fixtures.
        for cond in ('', 'eq', 'ne', 'cs', 'hs', 'cc', 'lo', 'mi', 'pl', 'vs', 'vc', 'hi', 'ls', 'ge', 'lt', 'gt', 'le', 'al'):
            for suffix in ('', '.w'):
                with self.subTest(cond=cond, suffix=suffix):
                    dis = f'08006000 <main>:\n 8006000: f000 f800 bl{cond}{suffix} 8006010 <worker>\n'
                    report = guard.analyze(dis, {'main': 8, 'worker': 128})
                    self.assertEqual(report['roots']['main']['known_frame_sum'], 136)


if __name__ == '__main__':
    unittest.main()
