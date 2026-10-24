"""Replay a MARP recording on the translated Black Tiger (Musashi) with the Z80 cycle budget, and check it follows.

    python tools/marp_replay.py fw666_blktiger_2006700_wolf184.zip [--ticks N] [--no-build]

The recording's inputs (tools/marp_inputs.py: a .inp or its .zip, format 3.5) go into build/blktiger/marp_inputs.bin, a
sim build with the cycle budget plays them (build.py --sim --cycles -D PLAYBACK=1 -D MARP=1: tools/cycle_budget.py,
cyc_poll in src/blktiger.s; no lives kept), and the board's lives, stage and score (8 digits at $E1E8, shown with a
trailing 0) are read at every idle point.  MARP lists the recording's final score (the file name's number): a port
that follows the recorded game frame for frame reaches it, and one that leaves it never does (without the budget the
game leaves 30 frames after the start press: F030Arcade docs/marp-replay.md, PORTING.md "Original CPU time and recorded
games").  No WolfMAME is needed for this check; a mismatch is located with F030Arcade's MAME dump workflow.

Port tick n gets the recording's frame n (F030Arcade: the frame counter $E003 agrees from power-on).
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from marp_inputs import inp_dsw, inp_inputs, runs  # noqa: E402
from paths import ROOT, build_dir  # noqa: E402
from sim import Sim, TRAP1  # noqa: E402
from machine68k import Register as R  # noqa: E402
from marp_reference import COLS  # noqa: E402
import numpy as np  # noqa: E402

LIVES, STAGE, SCORE = 0xf3a0, 0xf3a1, 0xe1e8


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', type=Path, help='a MARP .inp or .zip (format 3.5)')
    ap.add_argument('--ticks', type=int, help='stop after this many ticks (default: the whole recording)')
    ap.add_argument('--every', type=int, default=3600, help='print the state every n ticks')
    ap.add_argument('--shift', type=int, default=0, help='port tick n gets frame n + shift (negative: the first frame '
                    'repeated)')
    ap.add_argument('--no-build', action='store_true')
    ap.add_argument('--out', type=Path, help='the board state at each idle point (.npz: the tick, and the bytes of '
                    'marp_reference.COLS) for --compare')
    ap.add_argument('--compare', type=Path, help="a marp_reference.py --mame184 .npy of the same recording (its --shift "
                    "0 is this tool's --shift 1): the first tick whose state differs from the reference's frame")
    ap.add_argument('--ram', help='first-last tick: also save $E000-$FFFF at each idle point of these ticks (--out .ram.npz)')
    a = ap.parse_args()
    ram_lo, ram_hi = map(int, a.ram.split('-')) if a.ram else (-1, -1)
    rams, ram_ticks = [], []
    frames = inp_inputs(a.src)
    if a.shift > 0:
        frames = frames[a.shift:]
    elif a.shift < 0:
        frames = np.concatenate([frames[:1].repeat(-a.shift, 0), frames])
    m = re.search(r'_(\d+)_[a-z]+\d+\.(zip|inp)$', a.src.name)
    listed = int(m[1]) if m else None
    ticks = min(a.ticks or len(frames), len(frames))
    (build_dir('blktiger') / 'marp_inputs.bin').write_bytes(runs([(int(s), int(p)) for s, p in frames[:ticks]]))
    if not a.no_build:
        subprocess.run([sys.executable, str(Path(__file__).with_name('build.py')), '--sim', '--cycles',
                        '-D', 'PLAYBACK=1', '-D', 'MARP=1'], check=True, stdout=subprocess.DEVNULL)
    run = ROOT / 'run' / 'blktiger_sim_cyc'
    s = Sim(str(run / 'BLKTIGER.PRG'), run_dir=run)
    mem, cpu = s.mem, s.cpu
    mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('blktiger') / 'blktiger_sim_cyc.map').items()}
    mem.w16(sym['render_frame'], 0x4e75)           # (logic only: no drawing)
    dsw0, dsw1 = inp_dsw(a.src)                     # (the recording's DIP switches: ports 3 and 4)
    mem.w8(sym['bt_inputs'] + 3, dsw0)
    mem.w8(sym['bt_inputs'] + 4, dsw1)
    done, wait, bad = sym['sim_frame_done'], sym['sim_wait'], sym['z80_badpc']
    z = lambda addr: sym['g_block'] + addr - 0x8000

    def state():
        digits = bytes(mem.r_block(z(SCORE), 8))
        score = int(''.join(map(str, digits))) * 10 if all(d < 10 for d in digits) else -1
        return mem.r8(z(LIVES)), mem.r8(z(STAGE)), score

    t0, tick, last16 = time.monotonic(), 0, 0
    best, stages, deaths, prev, log = 0, {}, [], None, []
    cols = [z(c) for c in COLS]
    rows, row_ticks = [], []
    ref = np.load(a.compare) if a.compare else None
    first_diff = None
    while tick < ticks:
        while True:
            cpu.execute(4000)
            pc = cpu.r_pc()
            if pc == done:
                break
            if pc in (bad, bad + 2) or s.terminated:
                raise SystemExit(f'stopped at tick {tick}: {pc - s.base:06x} (z80_badpc: Z80 pc '
                                 f'{mem.r16(sym["g_dispatch_pc"]):04x} bank {mem.r8(sym["g_bank"])}), terminated {s.terminated}')
            if pc == wait:
                raise SystemExit('sim_wait reached: not a CYCLES sim build')
            if pc == TRAP1:
                s.gemdos()
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)
        c16 = mem.r16(sym['cnt_ticks'])
        tick += (c16 - last16) & 0xffff
        last16 = c16
        lives, stage, score = st = state()
        if ram_lo <= tick <= ram_hi:
            rams.append(bytes(mem.r_block(z(0xe000), 0x2000)))
            ram_ticks.append(tick)
        if a.out or ref is not None:
            row = [mem.r8(c) for c in cols]
            if a.out:
                rows.append(row)
                row_ticks.append(tick)
            # (the idle point lies inside a frame: a byte agrees when it equals the reference's at that frame's end or
            # the next one's)
            if ref is not None and first_diff is None and tick < len(ref):
                r0, r1 = ref[tick - 1], ref[tick]
                diffs = [COLS[c] for c in range(len(COLS)) if row[c] != r0[c] and row[c] != r1[c]]
                if diffs:
                    first_diff = dict(tick=tick, addresses=[f"{v:04x}" for v in diffs], port=bytes(row).hex(),
                                      reference=bytes(r0).hex(), next=bytes(r1).hex())
                    print('first difference', json.dumps(first_diff), flush=True)
        if score > best:
            best = score
        stages.setdefault(stage, tick)
        if prev and lives < prev[0] and prev[1] == stage:
            deaths.append(tick)
        if prev is None or tick // a.every != prev[3] // a.every:
            print(json.dumps(dict(tick=tick, lives=lives, stage=stage, score=score,
                                  ticks_per_s=round(tick / (time.monotonic() - t0)))), flush=True)
        prev = (*st, tick)
    result = dict(recording=a.src.name, ticks=tick, of=len(frames), listed_score=listed, best_score=best,
                  followed=best == listed if listed else None, stages_first_tick=stages, lives_lost=len(deaths),
                  seconds=round(time.monotonic() - t0))
    if ref is not None:
        result['first_difference'] = first_diff
    if rams:
        np.savez_compressed(a.out.with_suffix('.ram.npz'), ticks=np.array(ram_ticks),
                            ram=np.frombuffer(b''.join(rams), np.uint8).reshape(len(rams), -1))
    if a.out:
        np.savez_compressed(a.out, ticks=np.array(row_ticks), rows=np.array(rows, np.uint8))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
