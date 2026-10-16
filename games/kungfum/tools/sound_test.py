"""The STE's sound (src/sound.s: the translated driver and snd_ym, run/kungfum_sim on Musashi) against its model
(tools/sound.py STEBoard: the driver on the 6803 interpreter in the STE's schedule, YM), frame by frame.

    python sound_test.py [frames] [--seed N] [--random]

The commands: those the game sends (the reference's port schedule with ref/cover.py's inputs and cheats, seed N), or
with --random a random command each 30-90 frames (every command the driver has: all the tunes, effects and voices).  Each
frame: the commands into kf_sound's ring, snd_frame called; compared: the two AYs' registers, the YM's (the cache
snd_ym writes through) and its channel choice; then snd_mix makes MIX_N bytes of the voices: the DMA ring against
sound.VoiceMix.  Reports the 68000 cycles of snd_frame and snd_mix (Musashi).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from paths import ROOT, build_dir
import sound

BUILD = build_dir('kungfum')
MIX_N = 112                                 # (about the DMA's bytes in an arcade frame: 6258 / 56.34; a multiple of 4)


def game_commands(seed, frames):
    import cover
    from machine import KungFuPort
    m = KungFuPort(*cover.dsw(seed))
    rnd = random.Random(seed)
    st = {'select': seed in (12, 13)}
    for f in range(frames):
        m.system, m.p1 = cover.inputs(f, rnd, st, m)
        cover.cheats(seed, f, m, st)
        m.frame = f
        m.run_frame_port()
    out = [[] for _ in range(frames)]
    for f, v in m.sound_log:
        if 0 <= f < frames:
            out[f].append(v)
    return out


# the commands with a sequence or a sample: 0 (stop), 1-7 the voices (8-15: empty), $10-$24 the effects and tunes
# ($25-$3F point outside the program: the game never sends them)
VALID = list(range(0, 8)) + list(range(0x10, 0x25))


def random_commands(seed, frames):
    rnd = random.Random(seed)
    out = [[] for _ in range(frames)]
    f = 10
    while f < frames:
        v = rnd.choice(VALID)
        out[f] += [v, v | 0x80]
        f += rnd.randrange(30, 90)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=6000)
    ap.add_argument('--seed', type=int, default=4)
    ap.add_argument('--random', action='store_true')
    args = ap.parse_args()
    cmds = (random_commands if args.random else game_commands)(args.seed, args.frames)
    run = ROOT / 'run' / 'kungfum_sim'
    s = Sim(str(run / 'KUNGFUM.PRG'), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / 'kungfum_sim.map').items()}
    mem, cpu = s.mem, s.cpu

    def run_to(targets):
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(500).cycles
            pc = cpu.r_pc()
            if pc in targets:
                return total
            if pc in (sym['z80_badpc'], sym['z80_badpc'] + 4) or s.terminated:
                raise RuntimeError('stopped at %06x' % (pc - s.base))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('timeout')

    def call(label, d0=None):
        a7 = cpu.r_reg(R.A7)
        if d0 is not None:
            cpu.w_reg(R.D0, d0)
        sp = a7 - 64
        mem.w32(sp, sym['sim_render_ret'])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[label])
        n = run_to({sym['sim_render_ret']})
        cpu.w_reg(R.A7, a7)
        return n

    run_to({sym['sim_wait']})
    call('snd_init')
    b = sound.STEBoard()
    b.boot()
    vm = sound.VoiceMix(*sound.build_voices(BUILD))
    vbad = 0
    head = mem.r8(sym['snd_head'])
    mem.w8(sym['snd_tail'], head)
    bad = 0
    ram_bad = [False]
    cycles = []
    mix_cycles = []
    for f in range(args.frames):
        for v in cmds[f]:
            mem.w8(sym['snd_ring'] + head, v)
            head = (head + 1) & 0xFF
        mem.w8(sym['snd_head'], head)
        cycles.append(call('snd_frame'))
        b.frame(cmds[f])
        mix_cycles.append(call('snd_mix', MIX_N))
        for v in cmds[f]:
            if not v & 0x80:
                vm.command(v)
        vm.mix(MIX_N)
        if bytes(mem.r_block(sym['snd_ring_buf'], vm.RING)) != bytes(vm.ring) or mem.r16(sym['snd_wp']) != vm.wp:
            vbad += 1
        ram = bytes(mem.r_block(sym['mcu_mem'] + 0x80, 0x70))     # ($F0-$FF: the 6803's stack; the translation returns on the 68000's)
        if ram != bytes(b.cpu.ram[0x80:0xF0]) and not ram_bad[0]:
            ram_bad[0] = True
            d = [(hex(0x80 + i), ram[i], b.cpu.ram[0x80 + i]) for i in range(0x70) if ram[i] != b.cpu.ram[0x80 + i]]
            print('frame %d: the driver\'s RAM differs first: %s' % (f, d[:10]))
        ay = bytes(mem.r_block(sym['snd_ay'], 32))
        want_ay = bytes(b.ay[0].regs) + bytes(b.ay[1].regs)
        ym = list(mem.r_block(sym['snd_ym_cache'], 14))
        ch = [x - 256 if x > 127 else x for x in mem.r_block(sym['snd_ymch'], 3)]
        if ay != want_ay or ym != b.ym.cache[:14] or ch != b.ym.ch:
            bad += 1
            if bad <= 5:
                print('frame %d (commands %s): AY %s / %s, YM %s / %s, channels %s / %s' % (
                    f, cmds[f], ay.hex(), want_ay.hex(), ym, b.ym.cache[:14], ch, b.ym.ch))
    print('the voices: the DMA ring (%d bytes a frame) differs in %d frames; snd_mix %d cycles a frame (Musashi)' % (
        MIX_N, vbad, sum(mix_cycles) // len(mix_cycles)))
    bad += vbad
    cycles.sort()
    print('%s: %d frames (%s), %d differ; snd_frame %d cycles a frame on average, median %d, 99%% %d, max %d '
          '(Musashi)' % ('PASS' if not bad else 'FAIL', args.frames, 'random commands' if args.random else
                         'the game\'s commands, seed %d' % args.seed, bad, sum(cycles) // len(cycles),
                         cycles[len(cycles) // 2], cycles[len(cycles) * 99 // 100], cycles[-1]))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
