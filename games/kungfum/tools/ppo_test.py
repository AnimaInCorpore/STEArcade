"""Optional PPO environment contracts. Run in the PPO Python environment.

--mame additionally checks native repeatability, one-shot PC coverage and input
recording without a trained model. Requires the Kung-Fu Master ROMs and MAME.
"""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3]/'engine')]
import playbot
from ppo_env import ACTIONS, FEATURES, KungFuEnv, features, inputs
from ppo_mame import Mame


class Contracts(unittest.TestCase):
    def test_frame_inputs_roundtrip(self):
        frames=[]
        for action,(direction,button) in enumerate(ACTIONS):
            segment=inputs(action,len(frames)+900)
            for i,(_,byte) in enumerate(segment):
                self.assertEqual((~byte)&15,direction)
                self.assertEqual((~byte)&0xa0,button if i%4<2 else 0)
            frames.extend(segment)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'inputs.bin'; path.write_bytes(playbot.encode(frames))
            self.assertEqual(playbot.load(path),frames)

    def test_observation_excludes_reward_and_stack(self):
        state=dict(ram=bytes(0x2000),sprites=bytes(256),scroll=0,pcs=[0x38])
        a=features(state)
        self.assertEqual(a.shape,(FEATURES,))
        altered=bytearray(state['ram']); altered[-1]=255
        state.update(ram=bytes(altered),pcs=[0x38,0x1234])
        np.testing.assert_array_equal(features(state),a)
        altered[0x1000]=255; state['ram']=bytes(altered)
        self.assertEqual(features(state)[0],1)

    def test_bad_episode_length_rejected(self):
        for frames in (0,900,901):
            with self.assertRaises(ValueError): KungFuEnv('/tmp/unused',frames)


def native_smoke():
    with tempfile.TemporaryDirectory() as d:
        runs=[]
        for run in range(2):
            with Mame(Path(d)/str(run)) as m:
                states=[m.step(900),m.step(12,p1=0x7d),m.step(12,p1=0x7d)]
            assert not states[0]['pcs']
            assert states[1]['pcs'] and not set(states[1]['pcs']) & set(states[2]['pcs'])
            runs.append(states)
        assert runs[0]==runs[1], 'native MAME state/coverage is not repeatable'
    print('MAME repeatability and first-execution coverage: PASS')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mame',action='store_true')
    args=ap.parse_args()
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
    if not result.wasSuccessful(): sys.exit(1)
    if args.mame: native_smoke()
