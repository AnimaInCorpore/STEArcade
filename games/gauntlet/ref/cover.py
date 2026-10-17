"""Coverage of Gauntlet's main CPU program on the STE's schedule (tools/stemodel.py: the original program, the sound
board's model), so the runs are the games the STE and tools/logic_test.py play.

    venv/bin/python games/gauntlet/ref/cover.py SEED FRAMES      -> build/gauntlet/cover_SEED.pkl

Seeds: -1 the BIOS's boot on the reference board (tools/machine.py, as MAME); 0 the attract mode only; 1-9 random play (a coin and the start (MAGIC held) for player 1, the joystick and the buttons
changing every few frames, a coin again when the health runs low); 10-19 the same for 2-4 players.  Records:
  exec      set of the instruction addresses executed
  regions   {pc: bits}: the regions (machine.REGIONS) its data accesses touched, bit r read, 16 + r write
  banks     slapstic bank changes per frame (a list)
  sound     [(frame, command)]
"""
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import region_table
from stemodel import PortModel
from paths import build_dir

UP, DOWN, LEFT, RIGHT, FIRE, MAGIC = 0x80, 0x40, 0x20, 0x10, 0x02, 0x01
COIN_BITS = [0x08, 0x04, 0x02, 0x01]              # the sound CPU's 1020: coin 1-4 (player 1-4), active low


class Player:
    """random play of one player: a coin, the start (MAGIC held: the second button starts), then segments of a
    direction and the buttons"""

    def __init__(self, rnd, k, start):
        self.rnd, self.k, self.start = rnd, k, start
        self.bits = 0
        self.until = 0

    def coin(self, f):
        return self.start <= f < self.start + 6 or (f > self.start and (f - self.start) % 3000 < 6)

    def joy(self, f):
        if f < self.start + 100:
            return 0
        if f < self.start + 160:
            return MAGIC                               # the start (the second button)
        if f >= self.until:
            r = self.rnd
            d = r.choice([0, UP, DOWN, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT])
            self.bits = d | (FIRE if r.random() < 0.4 else 0) | (MAGIC if r.random() < 0.02 else 0)
            self.until = f + r.randint(4, 60)
        return self.bits


def run_boot(frames):
    """seed -1: the BIOS's boot on the reference board (as MAME): the STE skips it, but its routines stay patched"""
    from machine import Gauntlet
    m = Gauntlet()
    cov = m.cpu.coverage(region_table())
    m.cpu.trace(True)
    execd = set()
    for f in range(frames):
        m.run_frame()
        execd.update(pc for pc, _ in m.cpu.take_trace())
    regions = {int(pc) * 2: int(cov[pc]) for pc in np.nonzero(cov)[0]}
    p = build_dir("gauntlet") / "cover_-1.pkl"
    p.write_bytes(pickle.dumps(dict(exec=execd, regions=regions, banks=[], sound=m.sound_log)))
    print("seed -1 (boot): %d frames, %d instructions -> %s" % (frames, len(execd), p))


def run(seed, frames):
    if seed < 0:
        return run_boot(frames)
    rnd = random.Random(seed)
    m = PortModel(patched=False)
    cov = m.cpu.coverage(region_table())
    m.cpu.trace(True)
    execd = set()
    players = []
    if seed:
        n = 1 if seed < 10 else rnd.randint(2, 4)
        players = [Player(rnd, k, 300 + 50 * k) for k in range(n)]
    banks = []
    last = m.cpu.lib.m68k_slapstic_changes()
    for f in range(frames):
        for p in players:
            if p.coin(f) and not p.coin(f - 1):
                m.sound.coin(p.k)
            m.inputs[p.k] = 0xFFFF & ~p.joy(f)
        m.step()
        execd.update(pc for pc, _ in m.cpu.take_trace())
        n = m.cpu.lib.m68k_slapstic_changes()
        banks.append(n - last)
        last = n
    regions = {int(pc) * 2: int(cov[pc]) for pc in np.nonzero(cov)[0]}
    out = dict(exec=execd, regions=regions, banks=banks, sound=m.sound.commands)
    p = build_dir("gauntlet") / ("cover_%d.pkl" % seed)
    p.write_bytes(pickle.dumps(out))
    print("seed %d: %d frames, %d instructions, %d with data accesses, %d bank changes -> %s" % (
        seed, frames, len(execd), len(regions), sum(banks), p))


if __name__ == "__main__":
    run(int(sys.argv[1]), int(sys.argv[2]))
