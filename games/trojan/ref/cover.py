"""Bank-aware coverage of the main Z80 on the port schedule (tools/machine.py TrojanPort), reproducible random input.

    python games/trojan/ref/cover.py SEED [FRAMES]       -> build/trojan/cover<SEED>.pkl

Seeds 1-3: the attract mode, then coins, starts and random play (the game's own lives: game overs, the high score
entry when a score makes it).  Seeds 22-45: every level again with input periods 8, 20, 40, 16 frames.  Seeds 4-15: a game from the starting level (the DIP switch SWB 6-8, levels 1-6:
seed 4 + level - 1 and seed 10 + level - 1) with MAME's cheats (infinite lives $CDA0, energy $C078, time $C079: every
level's code runs, its boss included), the play mostly walking right with random attacks, jumps and turns (seeds
10-15 change the input faster).  Records (bank or -1, pc) of every instruction executed, the sites that read the ROM
window $8000-$BFFF as data (gen.py guards those), and the sites that store to the video RAM / palette / registers
(with the regions they write).
"""
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import TrojanPort, DSWA
from paths import build_dir

import os
SHOTS = os.environ.get("SHOTS")         # (a folder: the picture every 2000 frames)
LEVEL_DSW = {1: 0xE0, 2: 0xC0, 3: 0xA0, 4: 0x80, 5: 0x60, 6: 0x40}


def schedule(seed):
    """-> (level or None, cheats, the input function frame -> (SERVICE, P1)); seed 0: the AUTOPLAY schedule of
    src/trojan.s (tools/logic_test.py auto_inputs: the lives kept, nothing else)"""
    if seed == 0:
        from logic_test import auto_inputs
        return None, False, lambda f: auto_inputs(f)[:2]
    if seed == -1:                              # (the recorded play, tools/play_search.py: its lives kept)
        import playbot
        play = playbot.load(build_dir('trojan') / 'play_inputs.bin')
        return None, False, lambda f: play[f] if f < len(play) else (255, 255)
    rng = random.Random(seed)
    level = None
    if 4 <= seed <= 9:
        level = seed - 3
    elif 10 <= seed <= 15:
        level = seed - 9
    elif seed >= 22:
        level = (seed - 22) % 6 + 1            # (seeds 22-45: every level again, other input rates)
    period = 12 if seed >= 10 else 30
    if seed >= 22:
        period = (8, 20, 40, 16)[(seed - 22) // 6 % 4]
    state = {"p1": 0xFF}

    def inputs(f):
        sys_in = 0xFF
        if level is None:
            if f > 700 and f % 600 < 5:
                sys_in &= ~0x40                     # a coin (held 5 frames: the game wants it 2 frames low)
            if f > 700 and 40 <= f % 600 < 45:
                sys_in &= ~0x01                     # start 1
            if f > 700 and 80 <= f % 3000 < 85:
                sys_in &= ~0x02                     # (sometimes start 2)
            if f > 700 and f % period == 0:
                state["p1"] = 0xFF ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 33, 18, 34, 9, 5, 6, 10, 48])
            return sys_in, state["p1"]
        if 900 <= f < 905:
            sys_in &= ~0x40
        if 940 <= f < 945:
            sys_in &= ~0x01
        if f >= 1000 and f % period == 0:
            r = rng.random()
            if r < 0.55:
                p = 1 | (16 if rng.random() < 0.5 else 0) | (32 if rng.random() < 0.2 else 0)
            elif r < 0.7:
                p = rng.choice([4, 8, 9, 5, 20, 24])
            else:
                p = rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 33, 18, 34, 48, 6, 10])
            state["p1"] = 0xFF ^ p
        return sys_in, state["p1"]
    return level, level is not None, inputs


def run(seed, frames, log=print):
    level, cheats, inputs = schedule(seed)
    m = TrojanPort(DSWA, 0x1C | LEVEL_DSW[level] if level else 0xFC)
    c = m.cpu
    seen = set()
    wread = set()
    stores = {}                         # (bank, pc) -> set of regions ('fg', 'bg', 'pal', 'spr', 'reg')
    site = [(-1, 0), 0]                 # (bank, pc), its real pc
    read0, write0, step0 = m.rd, m.wr, c.step

    def rd(a):
        if 0x8000 <= a < 0xC000 and not site[1] <= a < site[1] + 4:
            wread.add(site[0])
        return read0(a)

    def wr(a, v):
        if a >= 0xDE00:
            r = ("spr" if a < 0xDF80 else "ram" if a < 0xE000 else "fg" if a < 0xE800 else "bg" if a < 0xF000
                 else "pal" if a < 0xF800 else "reg")
            if r != "ram":
                stores.setdefault(site[0], set()).add(r)
        return write0(a, v)

    def step():
        pc = c.pc
        site[0] = (m.bank if 0x8000 <= pc < 0xC000 else -1, pc)
        site[1] = pc
        seen.add(site[0])
        return step0()

    c.rd8, c.wr8, c.step = rd, wr, step
    m.rd, m.wr = rd, wr
    for f in range(frames):
        m.inputs[0], m.inputs[1] = inputs(f)
        if seed == 0 and f % 3000 >= 1000 or seed == -1 and f >= 1000:
            m.mem[0xCDA0] = 3
        if cheats and f >= 1000:
            m.mem[0xCDA0] = 3
            m.mem[0xC078] = 0
            m.mem[0xC079] = 0x99
        try:
            m.run_frame_port()
        except RuntimeError as e:
            log("seed %d frame %d: %s; stopped" % (seed, f, e))
            break
        if f % 2000 == 0:
            log("seed %d frame %d: %d bank/pc pairs" % (seed, f, len(seen)))
            if SHOTS and not m.regs["flip"]:
                from PIL import Image
                Image.fromarray(m.render_rgb()).save(Path(SHOTS) / ("cover%d_%05d.png" % (seed, f)))
    return {"pcs": seen, "wread": wread, "stores": stores, "seed": seed, "frames": frames, "level": level}


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    d = run(seed, frames, lambda s: print(s, flush=True))
    out = build_dir("trojan") / ("cover%d.pkl" % seed if seed >= 0 else "cover_play.pkl")
    with out.open("wb") as f:
        pickle.dump(d, f)
    print(out, len(d["pcs"]), "pairs")


if __name__ == "__main__":
    main()
