"""The table helpers emitted in place (gen.py TrEmitter.x_rst: rst $18 / $20 / $28 / $30 where the flags they leave are
dead) against the Z80 running the ROM's helpers (engine/z80.py), at their sites in the sim build (run/trojan_sim);
then the natives (gen.py NATIVES, src/natives.s) from their labels to their continuations.

    python games/trojan/tools/native_test.py [N]

For each in-place site (fixed and banked code, every helper) N random states: A, HL (the pointers often near a page
end: the carry into H), DE, the RAM, the bank; the 68000 code runs from the site's label to the return point (rst $30:
to the dispatch of its target); A, DE, HL and the RAM must equal the Z80's after `rst` and its helper ran to the
return (rst $30: to the jump), the flags not compared (dead there by construction).
"""
from pathlib import Path
import json
import random
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from machine import TrojanPort
from paths import ROOT, build_dir
from profile import z80_labels
import gen


def sites():
    """{virtual pc: helper} of the in-place helpers (their code holds no `move.w #ret,-(a5)`)"""
    out, cur, body = {}, None, []
    for line in (build_dir('trojan') / 'code_trojan.s').read_text().splitlines() + ['Z0:']:
        m = re.match(r'^Z([0-9A-F]{4,5}):\t*(; (.*))?', line)
        if m:
            if cur is not None and re.fullmatch(r'rst \$(18|20|28|30)', cur[1] or ''):
                if not any('-(a5)' in b for b in body):
                    out[cur[0]] = int(cur[1][-2:], 16)
            cur, body = (int(m[1], 16), m[3]), []
        else:
            body.append(line)
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    run = ROOT / 'run' / 'trojan_sim'
    sim = Sim(str(run / 'TROJAN.PRG'), ram_kib=16384, run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('trojan') / 'trojan_sim.map').items()}
    mem, cpu = sim.mem, sim.cpu
    label = {pc: sim.base + off for off, pc in z80_labels()}
    block = sym['g_block']
    z = lambda a: block + 0x8000 + (a if a < 0x8000 else a - 0x10000)
    dispatch = sym['tr_dispatch']
    rnd = random.Random(1)
    found = sites()
    rst30 = {int(k, 16): v for k, v in json.loads((build_dir('trojan') / 'rst30.json').read_text()).items()}
    tested = {0x18: 0, 0x20: 0, 0x28: 0, 0x30: 0}
    for pc, helper in sorted(found.items()):
        bank = (pc - gen.VBASE) // 0x4000 if pc >= gen.VBASE else 0
        rpc = gen.real(pc)
        nxt = pc + 1
        for _ in range(n):
            m = TrojanPort()
            m.bank = bank
            ram = bytes(rnd.randrange(256) for _ in range(0x2000))
            m.mem[0xC000:0xE000] = ram
            # (rst $30: an index into the site's table, as far as it goes: past its end lie the code's next bytes,
            # an index the game never computes)
            a = rnd.randrange(len(rst30[pc])) if helper == 0x30 else rnd.randrange(256)
            upper = [rnd.randrange(0x10000) for _ in range(3)]          # (BC' DE' HL': kept)
            while True:
                hl = rnd.choice([0xC000 + rnd.randrange(0x1F00), 0xC0F0 + rnd.randrange(16),
                                 0x8000 + rnd.randrange(0x3F00) if helper in (0x20, 0x28) else 0xD000 + rnd.randrange(0x100)])
                # (not a table in the return addresses the Z80's rsts push below SP, $CFEC-$CFEF here (rst $28 calls
                # rst $18), which the code in place does not push: the game's tables are never in the stack)
                at = hl + (a if helper == 0x20 else 2 * a & 255 if helper in (0x28, 0x30) else 0)
                if helper == 0x18 or not {at & 0xFFFF, (at + (helper != 0x20)) & 0xFFFF} & set(range(0xCFEC, 0xCFF0)):
                    break
            de = rnd.randrange(0x10000)
            c = m.cpu
            c.a, c.h, c.l, c.d, c.e = a, hl >> 8, hl & 255, de >> 8, de & 255
            c.sp = 0xCFF0
            c.pc = rpc
            target = None
            for _ in range(40):                     # the rst and its helper, to the return point / the jump
                c.step()
                if helper != 0x30 and c.pc == (rpc + 1) & 0xFFFF and c.sp == 0xCFF0:
                    break
                if helper == 0x30 and c.pc not in range(0x18, 0x34):
                    target = c.pc
                    break
            else:
                raise RuntimeError('%05X: the Z80 did not return' % pc)
            # the 68000: the same state
            mem.w_block(z(0xC000), ram)
            mem.w8(sym['g_bank'], bank * 4)
            mem.w32(sym['g_winbase'], mem.r32(sym['tr_winbases'] + 4 * bank))
            mem.w32(sym['g_wdispatch'], mem.r32(sym['tr_dispatch_targets'] + 4 * bank))
            cpu.w_reg(R.D0, a)
            cpu.w_reg(R.D1, upper[0] << 16 | rnd.randrange(0x10000))
            cpu.w_reg(R.D2, upper[1] << 16 | de)
            cpu.w_reg(R.D3, upper[2] << 16 | hl)
            cpu.w_reg(R.A5, z(0xCFF0))
            cpu.w_reg(R.A6, block + 0x8000)
            cpu.w_reg(R.A4, sym['tr_fixed_dispatch'])
            cpu.w_reg(R.A7, sym['own_stack_top'])
            cpu.w_pc(label[pc])
            stop = dispatch if helper == 0x30 else label[nxt]
            for _ in range(200):
                cpu.execute(1)
                if cpu.r_pc() == stop:
                    break
            else:
                raise RuntimeError('%05X: the 68000 code did not reach its end' % pc)
            got = (cpu.r_reg(R.D0) & 255, cpu.r_reg(R.D2) & 0xFFFF, cpu.r_reg(R.D3) & 0xFFFF,
                   *(cpu.r_reg(r) >> 16 for r in (R.D1, R.D2, R.D3)))
            want = (c.a, c.d << 8 | c.e, c.h << 8 | c.l, *upper)
            if helper == 0x30:
                got += (cpu.r_reg(R.D7) & 0xFFFF,)
                want += (target,)
            g, w = bytearray(mem.r_block(z(0xC000), 0x2000)), bytearray(m.mem[0xC000:0xE000])
            g[0xF80:0xFF0] = w[0xF80:0xFF0] = bytes(0x70)      # (the stack below SP: dead)
            if got != want or g != w:
                print('FAIL %05X rst $%02X: A HL=%02X %04X: 68000 %s, Z80 %s' % (pc, helper, a, hl,
                      ' '.join('%X' % v for v in got), ' '.join('%X' % v for v in want)))
                return 1
        tested[helper] += 1
    print('PASS: %s in-place sites x %d random states' % (', '.join('rst $%02X %d' % kv for kv in tested.items()), n))
    # the natives (gen.py NATIVES): from the routine's label to its continuation, against the Z80
    for start, stop, states in ((0x1E95, 0x1EA2, ldi4_states(rnd, 50 * n)),):
        for bank, a, bc, de, hl in states:
            m = TrojanPort()
            m.bank = bank
            ram = bytes(rnd.randrange(256) for _ in range(0x2000))
            m.mem[0xC000:0xE000] = ram
            c = m.cpu
            c.a, c.b, c.c, c.d, c.e, c.h, c.l = a, bc >> 8, bc & 255, de >> 8, de & 255, hl >> 8, hl & 255
            c.sp = 0xCFF0
            c.pc = start
            for _ in range(20000):
                c.step()
                if c.pc == stop and c.sp == 0xCFF0:
                    break
            else:
                raise RuntimeError('%04X: the Z80 did not get to %04X' % (start, stop))
            mem.w_block(z(0xC000), ram)
            mem.w8(sym['g_bank'], bank * 4)
            mem.w32(sym['g_winbase'], mem.r32(sym['tr_winbases'] + 4 * bank))
            mem.w32(sym['g_wdispatch'], mem.r32(sym['tr_dispatch_targets'] + 4 * bank))
            upper = [rnd.randrange(0x10000) for _ in range(3)]          # (BC' DE' HL': kept)
            cpu.w_reg(R.D0, a)
            cpu.w_reg(R.D1, upper[0] << 16 | (bc & 255) << 8 | bc >> 8)
            cpu.w_reg(R.D2, upper[1] << 16 | de)
            cpu.w_reg(R.D3, upper[2] << 16 | hl)
            cpu.w_reg(R.A5, z(0xCFF0))
            cpu.w_reg(R.A6, block + 0x8000)
            cpu.w_reg(R.A4, sym['tr_fixed_dispatch'])
            cpu.w_reg(R.A7, sym['own_stack_top'])
            cpu.w_pc(label[start])
            for _ in range(200000):
                cpu.execute(1)
                if cpu.r_pc() == label[stop]:
                    break
            else:
                raise RuntimeError('%04X: the 68000 code did not get to %04X' % (start, stop))
            d1 = cpu.r_reg(R.D1) & 0xFFFF
            got = (cpu.r_reg(R.D0) & 255, (d1 & 255) << 8 | d1 >> 8, cpu.r_reg(R.D2) & 0xFFFF, cpu.r_reg(R.D3) & 0xFFFF,
                   *(cpu.r_reg(r) >> 16 for r in (R.D1, R.D2, R.D3)))
            want = (c.a, c.b << 8 | c.c, c.d << 8 | c.e, c.h << 8 | c.l, *upper)
            g, w = bytearray(mem.r_block(z(0xC000), 0x2000)), bytearray(m.mem[0xC000:0xE000])
            g[0xF80:0xFF0] = w[0xF80:0xFF0] = bytes(0x70)
            if got != want or g != w:
                print('FAIL native %04X: bank %d BC DE HL=%04X %04X %04X: 68000 %s, Z80 %s' % (
                    start, bank, bc, de, hl, ' '.join('%X' % v for v in got), ' '.join('%X' % v for v in want)))
                return 1
        print('PASS: native %04X x %d states' % (start, len(states)))
    return 0


def ldi4_states(rnd, n):
    """$1E95's inputs: B bytes from DE (RAM, the fixed ROM, the bank window, some across a boundary) to HL in RAM"""
    out = []
    for i in range(n):
        b = rnd.choice([0, 1, 2, rnd.randrange(256)])
        span = 4 * (b or 256)
        hl = 0xC000 + rnd.randrange(0xCF80 - 0xC000 - span)
        de = rnd.choice([0xC000 + rnd.randrange(0x1E00), rnd.randrange(0x7F00), 0x8000 + rnd.randrange(0x3F00),
                         0x7FFF - rnd.randrange(8), 0xBFFF - rnd.randrange(8), 0xDFFF - rnd.randrange(8)])
        out.append((rnd.randrange(4), rnd.randrange(256), b << 8 | rnd.randrange(256), de, hl))
    return out


if __name__ == '__main__':
    sys.exit(main())
