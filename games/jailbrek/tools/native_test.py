"""The natives (gen.py NATIVES): nat_sn_AF96 and its inline forms (src/sound.s), nat_9272 (src/natives.s) against the 6809 running the ROM's routine at $AF96 (machine.JailBreak, the
reference CPU), outside the game: every byte value, random register files, latches and entry flags.

    python games/jailbrek/tools/native_test.py [N]

The 6809 runs from $AF96 to its RTS (the reference stops when the return address is reached: A, N Z V C, and the
bytes written to $3100 / $3200 are taken); the 68000 from the native's label to the RTS's translation (patched to stop
there).  Compared: A, N Z V C, and the SN76489A's register file (jb_sn, kept by the native; the expected one by MAME's
sn76496_base_device::write from the written byte), the latched register, the dirty flag.
"""
from pathlib import Path
import random
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import JailBreak
from paths import ROOT, build_dir

RET = 0x7F00                        # (a return address pushed for the 6809: the reference stops when it gets there)


def sn_write(regs, latch, v):
    """MAME's sn76496 write on a register file (8 words: periods 0, 2, 4, the noise control 6; volumes 1, 3, 5, 7)"""
    regs = list(regs)
    if v & 0x80:
        latch = v >> 4 & 7
        regs[latch] = regs[latch] & 0x3F0 | v & 15
    elif latch & 1 or latch == 6:
        regs[latch] = regs[latch] & 0x3F0 | v & 15
    else:
        regs[latch] = regs[latch] & 15 | (v & 0x3F) << 4
    return regs, latch


def main_sn():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    run = ROOT / 'run' / 'jailbrek_sim'
    sim = Sim(str(run / 'JAILBREK.PRG'), ram_kib=16384, run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('jailbrek') / 'jailbrek_sim.map').items()}
    mem, cpu = sim.mem, sim.cpu
    base = sym['jb_mem']
    stop = sym['M00AFA1']
    mem.w16(stop, 0x60FE)                           # bra.s * (the RTS not run: the test reads the state there)
    ref = JailBreak()
    rnd = random.Random(7)
    bad = 0
    cases = [(v, rnd.randrange(8), rnd.randrange(2)) for v in range(256) for _ in range(2)]
    cases += [(rnd.randrange(256), rnd.randrange(8), rnd.randrange(2)) for _ in range(n)]
    for v, latch, c_in in cases:
        regs = [rnd.randrange(1024) if i % 2 == 0 and i < 6 else rnd.randrange(16) for i in range(8)]
        # the 6809
        ref.mem[:] = bytes(rnd.randrange(256) for _ in range(0x10000))
        ref.mem[0x8000:] = ref.rom[0x8000:]
        ref.sound_log = []
        c = ref.cpu
        c.a, c.b, c.x, c.y, c.u, c.dp = v, rnd.randrange(256), rnd.randrange(65536), rnd.randrange(65536), 0, 0x15
        c.cc = 0x50 | c_in | rnd.choice((0, 2, 4, 8))
        c.s = 0x16FE
        ref.mem[0x16FE], ref.mem[0x16FF] = RET >> 8, RET & 255
        c.pc = 0xAF96
        for _ in range(200):
            c.step()
            if c.pc == RET:
                break
        else:
            raise RuntimeError('6809: no return from AF96')
        want = (c.a, c.cc & 0x0F, [x[2] for x in ref.sound_log if x[1] == 'sn'])
        wregs, wlatch = regs, latch
        for b in want[2]:
            wregs, wlatch = sn_write(wregs, wlatch, b)
        # the 68000: the entry from the 6809 (its RTS translation patched to stop), the inline forms (a return address)
        for entry in ('nat_sn_AF96', 'nat_sn_AF96_i', 'nat_sn_AF96_i_nf'):
            for i, w in enumerate(regs):
                mem.w16(sym['jb_sn'] + 2 * i, w)
            mem.w8(sym['snd_sn_latch'], latch)
            mem.w8(sym['snd_dirty'], 0)
            for r in (R.D1, R.D2, R.D3, R.D4):
                cpu.w_reg(r, rnd.randrange(1 << 32))
            cpu.w_reg(R.D0, v)
            cpu.w_reg(R.A5, base + 0x1700)
            cpu.w_reg(R.A4, base)
            cpu.w_sr(0x2700 | (0x11 if c_in else 0))
            if entry != 'nat_sn_AF96':
                sp = cpu.r_reg(R.A7) - 4
                cpu.w_reg(R.A7, sp)
                mem.w32(sp, stop)
            cpu.w_pc(sym[entry])
            for _ in range(100):
                cpu.execute(100)
                if cpu.r_pc() == stop:
                    break
                if cpu.r_pc() == TRAP1 or sim.terminated:
                    raise RuntimeError('stopped at %06x' % (cpu.r_pc() - sim.base))
            else:
                raise RuntimeError('native: no end')
            if entry != 'nat_sn_AF96':
                cpu.w_reg(R.A7, cpu.r_reg(R.A7) + 4)
            sr = cpu.r_sr()
            got_cc = (sr & 0x0F)
            gregs = [mem.r16(sym['jb_sn'] + 2 * i) for i in range(8)]
            problems = []
            if gregs != wregs:
                problems.append('SN %s, expected %s' % (gregs, wregs))
            if mem.r8(sym['snd_sn_latch']) != wlatch:
                problems.append('latch %d, expected %d' % (mem.r8(sym['snd_sn_latch']), wlatch))
            if not mem.r8(sym['snd_dirty']):
                problems.append('not dirty')
            if cpu.r_reg(R.D0) & 255 != want[0]:
                problems.append('A %02x, 6809 %02x' % (cpu.r_reg(R.D0) & 255, want[0]))
            # N Z V C: the 68000's CCR has N bit 3, Z bit 2, V bit 1, C bit 0; the 6809's CC N bit 3, Z bit 2, V bit 1, C bit 0
            if got_cc != want[1] and not entry.endswith('_nf'):
                problems.append('NZVC %x, 6809 %x' % (got_cc, want[1]))
            if problems:
                bad += 1
                if bad <= 8:
                    print('%s byte %02x latch %d C %d: %s' % (entry, v, latch, c_in, '; '.join(problems)))
    print('%s: nat_sn_AF96 (three entries), %d states, %d differ' % ('PASS' if not bad else 'FAIL', len(cases), bad))
    return int(bad != 0)


def main_9272():
    """nat_9272 against the 6809's $9272-$92C0: random objects and priorities, registers, flags"""
    run = ROOT / 'run' / 'jailbrek_sim'
    sim = Sim(str(run / 'JAILBREK.PRG'), ram_kib=16384, run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('jailbrek') / 'jailbrek_sim.map').items()}
    mem, cpu = sim.mem, sim.cpu
    base = sym['jb_mem']
    stop = sym['M0092C2']
    mem.w16(stop, 0x60FE)
    ref = JailBreak()
    rnd = random.Random(11)
    bad = 0
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    for case in range(n):
        ram = bytearray(rnd.randrange(256) for _ in range(0x2000))
        for k in range(8):
            ram[0x11C0 + 0x40 * k + 0x10] = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 2, 3, 3, 8, 255))
        x0 = rnd.choice((0x1000, 0x1100))
        a, b, y, u = rnd.randrange(256), rnd.randrange(256), rnd.randrange(65536), rnd.randrange(65536)
        cc = rnd.randrange(256)
        ref.mem[:0x2000] = ram
        c = ref.cpu
        c.a, c.b, c.x, c.y, c.u, c.dp, c.cc, c.s = a, b, x0, y, u, 0x15, cc, 0x16FE
        c.pc = 0x9272
        for _ in range(5000):
            c.step()
            if c.pc == 0x92C2:
                break
        else:
            raise RuntimeError('6809: no end')
        want_ram = bytes(ref.mem[:0x2000])
        mem.w_block(base, bytes(ram))
        for r, v in ((R.D0, a), (R.D1, b), (R.D2, x0), (R.D3, y), (R.D4, u)):
            cpu.w_reg(r, v)
        cpu.w_reg(R.A5, base + 0x16FE)
        cpu.w_reg(R.A4, base)
        cpu.w_sr(0x2700 | (cc & 0x1F))
        cpu.w_pc(sym['nat_9272'])
        for _ in range(100):
            cpu.execute(500)
            if cpu.r_pc() == stop:
                break
            if cpu.r_pc() == TRAP1 or sim.terminated:
                raise RuntimeError('stopped at %06x' % (cpu.r_pc() - sim.base))
        else:
            raise RuntimeError('native: no end')
        got_ram = bytes(mem.r_block(base, 0x2000))
        problems = []
        for name, r, w, m in (('A', R.D0, c.a, 255), ('B', R.D1, c.b, 255), ('X', R.D2, c.x, 65535), ('Y', R.D3, c.y, 65535), ('U', R.D4, c.u, 65535)):
            if cpu.r_reg(r) & m != w:
                problems.append('%s %x, 6809 %x' % (name, cpu.r_reg(r) & m, w))
        if cpu.r_sr() & 0x0F != c.cc & 0x0F:
            problems.append('NZVC %x, 6809 %x' % (cpu.r_sr() & 0x0F, c.cc & 0x0F))
        diff = [i for i in range(0x2000) if got_ram[i] != want_ram[i] and i != 0x16FD]     # (PSHS A's byte below the stack)
        if diff:
            problems.append('RAM differs at %s' % ' '.join('%04X' % i for i in diff[:6]))
        if problems:
            bad += 1
            if bad <= 8:
                print('nat_9272 case %d: %s' % (case, '; '.join(problems)))
    print('%s: nat_9272, %d states, %d differ' % ('PASS' if not bad else 'FAIL', n, bad))
    return int(bad != 0)


def main():
    return main_sn() | main_9272()


if __name__ == '__main__':
    sys.exit(main())
