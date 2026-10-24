"""Machine frames require encoded stack and return provenance, not SP spelling."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('guard', ROOT / 'tools/stack_usage_guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def block(words):
    return '08006000 <leaf>:\n' + '\n'.join(
        f' {0x8006000 + 2*i:x}: {word} {text}' for i, (word, text) in enumerate(words)) + '\n'


class MachineFrameTests(unittest.TestCase):
    def test_zero_leaf_and_literal_load(self):
        for words in [[('4770', 'bx lr')],
                      [('4b01', 'ldr r3, [pc, #4]'), ('6818', 'ldr r0, [r3]'), ('4770', 'bx lr')]]:
            report = guard.analyze(block(words), {})
            self.assertEqual(report['frames']['leaf'], 0)
            self.assertNotIn('leaf', report['missing_frames'])

    def test_stack_peak_and_return_provenance(self):
        words = [('b5f8', 'push {r3, r4, r5, r6, r7, lr}'), ('bf00', 'nop'),
                 ('bcf8', 'pop {r3, r4, r5, r6, r7}'), ('bc08', 'pop {r3}'),
                 ('469e', 'mov lr, r3'), ('4770', 'bx lr')]
        report = guard.analyze(block(words), {})
        self.assertEqual(report['frames']['leaf'], 24)
        self.assertEqual(report['machine_frame_evidence']['leaf']['code_hex'],
                         'f8b500bff8bc08bc9e467047')

    def test_reject_unknown_and_bad_stack(self):
        cases = [ [('b401', 'push {r0}'), ('4770', 'bx lr')],
                  [('bc01', 'pop {r0}'), ('4770', 'bx lr')],
                  [('4685', 'mov sp, r0'), ('4770', 'bx lr')],
                  [('4686', 'mov lr, r0'), ('4770', 'bx lr')],
                  [('bf08', 'it eq'), ('4770', 'bxeq lr')],
                  [('e7fe', 'b.n 8006000 <leaf>')],
                  [('4798', 'blx r3'), ('4770', 'bx lr')],
                  [('df00', 'svc 0'), ('4770', 'bx lr')],
                  [('be00', 'bkpt 0'), ('4770', 'bx lr')],
                  [('b501', 'push {r0, lr}'), ('bd02', 'pop {r1, pc}')],
                  [('2000', 'movs r0, #0')],
                  [('b080', 'sub sp, #0'), ('4770', 'bx lr')] ]
        # A balanced POP-PC is intentionally outside this limited proof.
        for words in cases:
            with self.subTest(words=words):
                self.assertIn('leaf', guard.analyze(block(words), {})['missing_frames'])

    def test_gaps_truncation_and_raw_opcode_win(self):
        for text in [block([('bf00', 'nop'), ('4770', 'bx lr')]).replace('8006002:', '8006004:'),
                     '08006000 <leaf>:\n ...\n 8006002: 4770 bx lr\n',
                     block([('4685', 'nop'), ('4770', 'bx lr')]),
                     '08006000 <leaf>:\n 8006000: f3af 8000 nop.w\n 8006004: 4770 bx lr\n']:
            self.assertIn('leaf', guard.analyze(text, {})['missing_frames'])

    def test_compiler_frame_and_other_gaps_retained(self):
        text = block([('4770', 'bx lr')]) + '08006010 <main>:\n 8006010: 4798 blx r3\n'
        report = guard.analyze(text, {'leaf': 32, 'main': 8})
        self.assertEqual(report['frames']['leaf'], 32)
        self.assertTrue(report['indirect_transfers'])
        self.assertFalse(report['complete'])

    def test_nested_push_peak_and_destroyed_return_token(self):
        words = [('b500', 'push {lr}'), ('b401', 'push {r0}'),
                 ('bc01', 'pop {r0}'), ('bc08', 'pop {r3}'),
                 ('469e', 'mov lr, r3'), ('4770', 'bx lr')]
        self.assertEqual(guard.analyze(block(words), {})['frames']['leaf'], 8)
        # Overwrite the saved LR value before copying it back to LR.
        words.insert(4, ('2300', 'movs r3, #0'))
        self.assertIn('leaf', guard.analyze(block(words), {})['missing_frames'])

    def test_exception_entry_odd_address_and_missing_return_rejected(self):
        text = block([('4770', 'bx lr')])
        for bad in [text.replace('leaf', 'HardFault_Handler'),
                    text.replace('08006000', '08006001').replace('8006000:', '8006001:'),
                    block([('bf00', 'nop')])]:
            self.assertTrue(guard.analyze(bad, {})['missing_frames'])

    def test_call_path_uses_proven_nonzero_frame(self):
        text = '08005ff0 <main>:\n 8005ff0: f000 f806 bl 8006000 <leaf>\n'
        text += block([('b501', 'push {r0, lr}'), ('bc09', 'pop {r0, r3}'),
                       ('469e', 'mov lr, r3'), ('4770', 'bx lr')])
        report = guard.analyze(text, {'main': 16})
        self.assertEqual(report['roots']['main']['known_frame_sum'], 24)
        self.assertEqual(report['root_gaps']['main']['missing_frames'], [])


if __name__ == '__main__':
    unittest.main()
