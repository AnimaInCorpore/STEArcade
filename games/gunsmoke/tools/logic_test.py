"""Frame-by-frame translated CPU against the reference (run_frame_port), through attract mode, coin / start and play.

    python logic_test.py [frames] [--seed N]     (seeds as ref/cover.py: 4-14 play with MAME's cheats from a round on)

Compared every frame: the RAM E000-FFFF, the video RAM D000-D802, the latches C804 / D806, the bank and the sprite
latch; the stack bytes only a merged `push rr; pop rr'` would have written (dead below SP) are left out.  Every change
of the text RAM must come with fg_written (the translated writers, gen.py text_sites).
"""
from pathlib import Path
import argparse
import pickle
import random
import re
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import GunSmoke
from paths import ROOT, build_dir
import cover


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--audit', action='store_true', help="record the translated instructions that read the block's own window area "
                    "(a read there is a site gen.py left unguarded) -> build/w_sites_audit_*.pkl")
    args = ap.parse_args()
    run = ROOT / 'run' / 'gunsmoke_sim'
    s = Sim(str(run / 'GUNSMOKE.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('gunsmoke') / 'gunsmoke_sim.map').items()}
    mem, cpu = s.mem, s.cpu
    mem.w16(sym['render_frame'], 0x4e75)
    wait, done, bad = sym['sim_wait'], sym['sim_frame_done'], sym['z80_badpc']
    a6 = sym['g_block'] + 0x8000

    def addr(a):
        return a6 + (a if a < 0x8000 else a - 0x10000)

    audit = {}
    if args.audit:
        import bisect
        labels = sorted((v, k) for k, v in sym.items() if re.fullmatch(r'Z[0-9A-F]{4,5}', k))
        lv = [v for v, _ in labels]
        on_access = s.on_access
        g0 = addr(0x8000)

        def watch(mode, width, a, value):
            if mode == 'R' and g0 <= a < g0 + 0x4000:
                i = bisect.bisect_right(lv, cpu.r_pc()) - 1
                if i >= 0:
                    audit[labels[i][1]] = audit.get(labels[i][1], 0) + 1
            return on_access(mode, width, a, value)
        mem.set_trace_func(watch)
        mem.set_trace_mode(True)

    m = GunSmoke()
    m.cpu.afmask = 0xc1
    rnd = random.Random(args.seed)
    cheats = args.seed >= 4
    if cheats:
        # MAME's start round cheat patches the operand of `ld hl,$8068` at 08C5: the same in the reference's ROM and in the
        # translated instruction (move.w #$8068,d3), the round's script pointer.
        start = cover.ROUNDS[min(args.seed - 4, len(cover.ROUNDS) - 1)]
        rom = bytearray(m.rom)
        rom[0x08c6:0x08c8] = start.to_bytes(2, 'little')
        m.rom = bytes(rom)
        site = sym['Z08C5']
        if mem.r16(site) != 0x363c or mem.r16(site + 2) != 0x8068:
            raise RuntimeError('Z08C5 is not move.w #$8068,d3')
        mem.w16(site + 2, start)
        for a in (0x08c6, 0x08c7):             # (and the ROM data the translation reads)
            mem.w8(addr(a), m.rom[a])
    # The translator merges `push rr; pop rr'` into a move (the stack word below SP is dead): those bytes are not
    # compared until another instruction writes them.
    merged = set()
    for line in (build_dir('gunsmoke') / 'code_gunsmoke.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4,5}):\t\t; push .* \(merged\)', line)
        if hit:
            pc = int(hit[1], 16)
            merged.add(pc)
    dead, site = set(), [0]
    step0, write0 = m.cpu.step, m.cpu.wr8

    def ref_step():
        pc = m.cpu.pc
        site[0] = 0x10000 + m.bank * 0x4000 + pc - 0x8000 if 0x8000 <= pc < 0xc000 else pc
        return step0()

    def ref_write(a, v):
        (dead.add if site[0] in merged else dead.discard)(a)
        return write0(a, v)

    m.cpu.step, m.cpu.wr8 = ref_step, ref_write

    cycles = [0]                               # (the 68000's cycles of the frames: the logic, no drawing)

    def run_to(targets):
        total = 0
        while total < 400_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                cycles[0] += total
                return pc
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError(f'CPU stopped at {pc - s.base:06x}, d7={cpu.r_reg(R.D7):08x}, log={s.log[-3:]}')
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError(f'CPU timeout at {cpu.r_pc() - s.base:06x}')

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def compare(f):
        for lo, hi in ((0xd000, 0xd803), (0xe000, 0x10000)):
            want = bytes(m.mem[lo:hi])
            got = bytes(mem.r_block(addr(lo), hi - lo))
            diff = [lo + i for i in range(hi - lo) if want[i] != got[i] and lo + i not in dead]
            if diff:
                raise RuntimeError(f'frame {f}: {len(diff)} RAM differences, pc {m.cpu.pc:04x} ' +
                                   str([(hex(a), hex(got[a - lo]), hex(want[a - lo])) for a in diff[:12]]))
        for name, a, want in (('C804', 0xc804, m.control), ('D806', 0xd806, m.layers)):
            if mem.r8(addr(a)) != want:
                raise RuntimeError(f'frame {f}: latch {name} {mem.r8(addr(a)):02x}, reference {want:02x}')
        if mem.r8(sym['g_bank']) != m.bank:
            raise RuntimeError(f'frame {f}: bank {mem.r8(sym["g_bank"])}, reference {m.bank}')
        sprites = bytes(b for off in range(0, 4096, 32) for b in m.sprites[off:off + 4])
        if bytes(mem.r_block(sym['sprite_buffer'], 512)) != sprites:
            raise RuntimeError(f'frame {f}: the sprite latch differs')

    last = [None]

    def text_flag(f):
        now = bytes(mem.r_block(addr(0xd000), 0x800))
        if last[0] is not None and now != last[0] and not mem.r8(sym['fg_written']):
            i = next(i for i in range(0x800) if now[i] != last[0][i])
            raise RuntimeError(f'frame {f}: {0xd000 + i:04x} changed without fg_written (a writer missing in gen.py)')
        last[0] = now
        mem.w8(sym['fg_written'], 0)

    run_to({wait})
    m.run_to_idle()
    m.booted = True
    compare(-1)
    text_flag(-1)
    state = {}
    cycles[0] = 0
    for f in range(args.frames):
        m.inputs[0], m.inputs[1] = cover.inputs(f, rnd, state)
        for a, v in zip((0xc000, 0xc001), m.inputs[:2]):
            mem.w8(addr(a), v)
        if cheats:
            m.mem[0xe040] = 6
            mem.w8(addr(0xe040), 6)
            if f % 300 == 0:
                m.mem[0xf790] = 1
                mem.w8(addr(0xf790), 1)
        mem.w8(sym['vbl_pending'], 1)
        m.run_frame_port()
        resume()
        run_to({done})
        compare(f)
        resume()
        run_to({wait})
        text_flag(f)
        if f % 1000 == 999:
            print(f'{f + 1} frames exact', flush=True)
    print(f'PASS: {args.frames} frames (seed {args.seed}, round pointer E06A {m.mem[0xe06a] | m.mem[0xe06b] << 8:04x}); '
          'RAM, video RAM, latches, bank and sprite latch exact; '
          'every text RAM change flagged')
    print(f'68000 cycles a frame (the game logic, no drawing; Musashi): {cycles[0] // args.frames}')
    if args.audit:
        out = build_dir('gunsmoke') / f'w_sites_audit_{args.seed}.pkl'
        out.write_bytes(pickle.dumps({int(k[1:], 16) for k in audit}))
        print('audit: reads of the unguarded window area by', len(audit), 'instructions', sorted(audit.items())[:20], '->', out)


if __name__ == '__main__':
    main()
