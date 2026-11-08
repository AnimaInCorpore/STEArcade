"""Regression for reports that preserve the desktop's 50/60/71 Hz mode."""
import unittest

from blittime import clock_calibration


class ClockCalibrationTests(unittest.TestCase):
    def test_darklord_60hz_return(self):
        text = '\n'.join([
            'CAL mode mfpCounts tosTicks vbls: 00000000 00002FF0 000000C8 0000003C ',
            'CAL mode mfpCounts tosTicks vbls: 00000001 00002FCD 000000C8 0000003C ',
            'CAL mode mfpCounts tosTicks vbls: 00000002 00002FF4 000000C8 0000003C ',
        ])
        self.assertEqual([r['inferred_video_hz'] for r in clock_calibration(text)], [60] * 3)

    def test_pal_and_monochrome_modes(self):
        for hz in [50, 71]:
            with self.subTest(hz=hz):
                text = '\n'.join(f'CAL mode mfpCounts tosTicks vbls: {m:08X} 00003000 000000C8 {hz:08X}' for m in range(3))
                self.assertEqual([r['inferred_video_hz'] for r in clock_calibration(text)], [hz] * 3)

    def test_bad_clock_or_changed_video_rate_is_rejected(self):
        for counts, rates in [(0, [60] * 3), (12288, [60, 50, 60]), (12288, [100] * 3)]:
            with self.subTest(counts=counts, rates=rates):
                text = '\n'.join(f'CAL mode mfpCounts tosTicks vbls: {m:08X} {counts:08X} 000000C8 {hz:08X}' for m, hz in enumerate(rates))
                with self.assertRaises(AssertionError):
                    clock_calibration(text)


if __name__ == '__main__':
    unittest.main()
