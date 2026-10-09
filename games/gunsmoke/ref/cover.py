"""Bank-aware main-Z80 coverage in the port's schedule (run_frame_port), with scripted play.

    python ref/cover.py <seed> <frames>  ->  build/gunsmoke/cover<seed>.pkl

pcs: (bank, pc) executed, bank -1 outside the window; wread: (bank, pc) of instructions that read the window as data;
writes: (bank, pc, address) of the stores to the latches C800-C806 and to the text RAM D000-D7FF (the instruction's
start pc); jumps: (bank, pc) where computed jumps went (jp (hl) / (ix) / (iy), the RAM trampoline at E0F8: call (E0F9)),
entries of the translation; sprites: a Counter of (code, y flip) of the sprites shown each frame (layers on, on the screen or its guard band),
which decide the generated sprite routines (tools/assets.py).  Seeds 1-3 play as they come (deaths, game over); seeds 4-14 use MAME's cheats (gunsmoke.xml: infinite
lives E040, invincibility 100B / 15F9 = ret, the start round at 08C6, a boss killed by one hit F790) to start at round
seed - 3 (14: the end sequence) and to go on through the following rounds.
"""
import pickle
from collections import Counter
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import GunSmoke
from paths import build_dir

ROUNDS = [0x8068, 0x8272, 0x849e, 0x8704, 0x89f6, 0x8ca4, 0x9536, 0x9890, 0x9b8a, 0x9eb8, 0xa1ee]


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1) active low; state: a dict the schedule keeps (attract, coin, play phases)."""
    system, p1 = 0xff, 0xff
    phase = state.setdefault('phase', 'attract')
    if phase == 'attract' and frame >= state.setdefault('coin_at', 700 + rnd.randrange(400)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4:
            system &= ~0x40                         # coin 1
        elif 40 <= t < 44:
            system &= ~0x01                         # start 1
        elif t >= 44:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame % 20 == 0:
            state['joy'] = rnd.choice([0, 0, 1, 2, 4, 8, 8, 8, 9, 10, 5, 6])
            state['fire'] = rnd.choice([0, 0x10, 0x20, 0x40, 0x20, 0x30, 0x60])
        p1 ^= state.get('joy', 0)
        if frame % 6 < 3:
            p1 ^= state.get('fire', 0)
        if frame - state['t0'] > 2500 and frame % 900 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (a coin and start again: continue / a new game)
    return system, p1


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = GunSmoke()
    cheats = seed >= 4
    if cheats:
        rom = bytearray(m.rom)
        rom[0x100b] = rom[0x15f9] = 0xc9
        start = ROUNDS[min(seed - 4, len(ROUNDS) - 1)]
        rom[0x08c6:0x08c8] = start.to_bytes(2, 'little')
        m.rom = bytes(rom)
    c = m.cpu
    pcs, wread, writes, jumps = set(), set(), set(), set()
    site = [(-1, 0)]
    step0, rd0, wr0 = c.step, m.rd8, m.wr8
    computed = [False]

    def step():
        pc = c.pc
        site[0] = (m.bank if 0x8000 <= pc < 0xc000 else -1, pc)
        pcs.add(site[0])
        if computed[0]:
            jumps.add(site[0])
        op = rd0(pc)
        computed[0] = pc == 0xe0f8 or op == 0xe9 or op in (0xdd, 0xfd) and rd0((pc + 1) & 0xffff) == 0xe9
        return step0()

    def rd8(a):
        if 0x8000 <= a < 0xc000:
            bank, pc = site[0]
            if not pc <= a < pc + 4:                # (not the instruction's own bytes)
                wread.add(site[0])
        return rd0(a)

    def wr8(a, v):
        if 0xc800 <= a <= 0xc806 or 0xd000 <= a < 0xd800:
            writes.add((*site[0], a))
        return wr0(a, v)

    c.step, c.rd8, c.wr8 = step, rd8, wr8
    sprites = Counter()
    state = {}
    for frame in range(frames):
        m.inputs[0], m.inputs[1] = inputs(frame, rnd, state)
        if cheats:
            m.mem[0xe040] = 6
            if frame % 300 == 0:
                m.mem[0xf790] = 1
        m.run_frame_port()
        if m.layers & 32:
            for off in range(0, 4096, 32):
                code, attr, sy, sx = m.sprites[off:off + 4]
                bank = attr >> 6
                if bank == 3:
                    bank += m.layers & 7
                top = 240 - (sx - ((attr & 32) << 3))
                if -16 < top < 256 and 0 < sy < 256:
                    sprites[(code + 256 * bank) % 2048, bool(attr & 16)] += 1
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} bank/PC pairs, banks {sorted({b for b, _ in pcs})}', flush=True)
    output = build_dir('gunsmoke') / f'cover{seed}.pkl'
    with output.open('wb') as f:
        pickle.dump({'pcs': pcs, 'wread': wread, 'writes': writes, 'jumps': jumps, 'sprites': sprites, 'io': m.io_log, 'seed': seed, 'frames': frames}, f)
    print(output, len(pcs))


if __name__ == '__main__':
    main()
