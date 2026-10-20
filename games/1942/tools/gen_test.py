"""Regression for the ending task missed by gameplay coverage: python gen_test.py."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen
from z80x import swap16


class EndingTaskTest(unittest.TestCase):
    def test_ending_task_has_dispatch_entry_without_coverage(self):
        # Remove the task from observed PCs even if future coverage includes it.
        coverage = gen.coverage
        def without_task():
            pcs, reads = coverage()
            return pcs - set(range(0x70F2, 0x7100)) - set(range(0x6EDA, 0x6F0E)), reads
        gen.coverage = without_task
        try:
            text, report, emitter, code = gen.generate()
        finally:
            gen.coverage = coverage
        for pc in (0x70F2, 0x70F5, 0x70F8, 0x70FB, 0x70FE):
            self.assertIn(pc, code)
        self.assertNotIn(0x70F2, emitter.no_entry)
        self.assertIn('Z70F2:', text)
        index = 0
        wanted = swap16(0x70F2)
        for line in text.split('z80_dispatch_sw:\n', 1)[1].splitlines():
            directive, value = line.strip().split(None, 1)
            count = int(value.split(',')[0]) if directive == 'dcb.l' else 1
            if index <= wanted < index + count:
                self.assertEqual((directive, value), ('dc.l', 'Z70F2'))
                break
            index += count
        else:
            self.fail('dispatch table ended before task entry')

        for pc in (0x6EDA, 0x6EEB):
            self.assertIn(pc, code)
            self.assertNotIn(pc, emitter.no_entry)
            self.assertIn('Z%04X:' % pc, text)
            index = 0
            wanted = swap16(pc)
            for line in text.split('z80_dispatch_sw:\n', 1)[1].splitlines():
                directive, value = line.strip().split(None, 1)
                count = int(value.split(',')[0]) if directive == 'dcb.l' else 1
                if index <= wanted < index + count:
                    self.assertEqual((directive, value), ('dc.l', 'Z%04X' % pc))
                    break
                index += count
            else:
                self.fail('dispatch table ended before score task entry')


if __name__ == '__main__':
    unittest.main()
