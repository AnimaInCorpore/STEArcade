"""The keyboard / joystick path (src/mikie.s acia_isr, key_table, compose_inputs) on Musashi: IKBD byte streams are fed
through a fake ACIA ($FFFC00 / $FFFC02), the composed in_sys / in_p1 / in_p2 (active low) are checked for every input of
both players, coins and starts: each key alone (make, then break), several keys together, both joysticks.

    python input_test.py [--tag mikie_sim]
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir

BUILD = build_dir('mikie')
SENTINEL = 0x00F00000       # (the return address of the fake exception: outside the program)

# (name, make scancode) -> (SYSTEM bit, P1 bit, P2 bit) pulled low
KEYS = [('P1 left', 0x4B, 0, 0x01, 0), ('P1 right', 0x4D, 0, 0x02, 0), ('P1 up', 0x48, 0, 0x04, 0), ('P1 down', 0x50, 0, 0x08, 0),
        ('P1 button 1 (space)', 0x39, 0, 0x10, 0), ('P1 button 1 (control)', 0x1D, 0, 0x10, 0), ('P1 button 1 (Z)', 0x2C, 0, 0x10, 0),
        ('P1 button 2 (alternate)', 0x38, 0, 0x20, 0), ('P1 button 2 (X)', 0x2D, 0, 0x20, 0),
        ('start 1', 0x02, 0x08, 0, 0), ('start 2', 0x03, 0x10, 0, 0), ('coin 1', 0x06, 0x01, 0, 0), ('coin 2', 0x07, 0x02, 0, 0),
        ('P2 left (keypad 4)', 0x6A, 0, 0, 0x01), ('P2 right (keypad 6)', 0x6C, 0, 0, 0x02), ('P2 up (keypad 8)', 0x68, 0, 0, 0x04),
        ('P2 down (keypad 2)', 0x6E, 0, 0, 0x08), ('P2 button 1 (keypad 0)', 0x70, 0, 0, 0x10), ('P2 button 2 (keypad .)', 0x71, 0, 0, 0x20)]


class Rig:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = Sim(str(run / 'MIKIE.PRG'), run_dir=run, ram_kib=16384)
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(BUILD / (tag + '.map')).items()}
        self.cpu, self.mem = self.s.cpu, self.s.mem
        self.queue = []
        self.mem.w16(SENTINEL, 0x60FE)      # (bra *: the fake exception returns here)
        self.mem.set_special_range_read_func(0xFF0000, 0, self.read)
        for n in ('sys_kbd', 'p1_kbd', 'p2_kbd', 'p1_joy', 'p2_joy', 'joy0_state', 'joy1_state', 'ikbd_state', 'ikbd_lost', 'ikbd_esc'):
            self.mem.w8(self.sym[n], 0)

    def read(self, addr):
        a = addr & 0xFFFFFF
        if a == 0xFFFC00:
            return 1 if self.queue else 0
        if a == 0xFFFC02:
            return self.queue.pop(0)
        return 0

    def feed(self, data):
        """the ACIA interrupt with these bytes -> (in_sys, in_p1, in_p2)"""
        self.queue = list(data)
        cpu, mem = self.cpu, self.mem
        sp = 0x00800000
        mem.w32(sp - 4, SENTINEL)
        mem.w16(sp - 6, 0x2300)
        cpu.w_reg(R.A7, sp - 6)
        cpu.w_sr(0x2700)
        cpu.w_pc(self.sym['acia_isr'])
        for _ in range(200):
            cpu.execute(500)
            if cpu.r_pc() == SENTINEL:
                break
        else:
            raise RuntimeError('acia_isr did not return (pc %x)' % cpu.r_pc())
        assert not self.queue, 'bytes left'
        return tuple(mem.r8(self.sym[n]) for n in ('in_sys', 'in_p1', 'in_p2'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', default='mikie_sim')
    args = ap.parse_args()
    r = Rig(args.tag)
    bad = 0

    def check(name, got, want):
        nonlocal bad
        if got != want:
            bad += 1
            print('FAIL %s: got %s, want %s' % (name, ['%02X' % x for x in got], ['%02X' % x for x in want]))
    idle = (0xFF, 0xFF, 0xFF)
    check('start', r.feed([]), (0xFF, 0xFF, 0xFF)) if False else None
    for name, code, sysb, p1b, p2b in KEYS:
        want = (0xFF & ~sysb, 0xFF & ~p1b, 0xFF & ~p2b)
        check(name + ' make', r.feed([code]), want)
        check(name + ' break', r.feed([code | 0x80]), idle)
    # all keys at once, released in reverse order
    allsys = allp1 = allp2 = 0
    for name, code, sysb, p1b, p2b in KEYS:
        allsys |= sysb; allp1 |= p1b; allp2 |= p2b
    check('all keys make', r.feed([k[1] for k in KEYS]), (0xFF & ~allsys, 0xFF & ~allp1, 0xFF & ~allp2))
    check('all keys break', r.feed([k[1] | 0x80 for k in reversed(KEYS)]), idle)
    # P1 and P2 together (the keys do not mix their players)
    check('P1 left + P2 right', r.feed([0x4B, 0x6C]), (0xFF, 0xFE, 0xFD))
    check('release', r.feed([0xCB, 0xEC]), idle)
    # the joysticks: port 1 plays player 1, port 0 player 2 (bits: up 0, down 1, left 2, right 3, fire 7)
    for jn, hdr, idx in (('joystick 1 -> P1', 0xFF, 1), ('joystick 0 -> P2', 0xFE, 2)):
        for bit, name, val in ((2, 'left', 0x01), (3, 'right', 0x02), (0, 'up', 0x04), (1, 'down', 0x08), (7, 'fire', 0x10)):
            want = [0xFF, 0xFF, 0xFF]
            want[idx] = 0xFF & ~val
            check('%s %s' % (jn, name), r.feed([hdr, 1 << bit]), tuple(want))
            check('%s %s released' % (jn, name), r.feed([hdr, 0]), idle)
    print('FAIL: %d mismatches' % bad if bad else 'PASS: %d keys (make / break), all keys together, both players, both joysticks' % len(KEYS))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
