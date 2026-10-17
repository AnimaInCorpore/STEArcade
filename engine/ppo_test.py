"""Shared PPO profile/replay contracts; no Torch, ROMs or emulator required."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import port
from ppo_profiles import profile,actions,boot_inputs
from playbot import encode,load


class Contracts(unittest.TestCase):
    def test_profiles_cover_registered_ports(self):
        for game in port.GAMES:
            p=profile(game)
            if game=='galaga':self.assertTrue(p['deferred']);continue
            self.assertTrue(p['ram'])
            self.assertGreater(sum(r[1] for r in p['ram']),0)
            self.assertLessEqual(max(r[1] for r in p['ram']),65535)
            self.assertTrue(all(0<=v<=255 for macro in actions(p) for v in macro))
            self.assertTrue(all(len(macro)==12 for macro in actions(p)))

    def test_native_coin_start_polarities(self):
        for game in port.GAMES:
            p=profile(game)
            if p.get('deferred'):continue
            idle=boot_inputs(p,p['start']+20)
            coin=boot_inputs(p,p['coin'])
            self.assertEqual(idle[0]^coin[0],p['coin_mask'],game)
            start=boot_inputs(p,p['start'])
            index=1 if p['start_source']=='p1' else 0
            self.assertEqual(idle[index]^start[index],p['start_mask'],game)

    def test_profiles_keep_existing_rle_encoding(self):
        with tempfile.TemporaryDirectory() as name:
            f=Path(name)/'replay.bin'
            for game in port.GAMES:
                p=profile(game)
                if p.get('deferred'):continue
                inputs=[boot_inputs(p,t) for t in range(p['boot'])]
                inputs += [(p['system_idle'],v) for m in actions(p) for v in m]
                f.write_bytes(encode(inputs))
                self.assertEqual(load(f),inputs)
                self.assertEqual(f.read_bytes()[-1],0)


if __name__=='__main__':unittest.main()
