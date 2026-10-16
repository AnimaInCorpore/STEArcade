"""Coverage of Double Dragon's main CPU program on the port's schedule (tools/machine.py DDragonPort).

    venv/bin/python games/ddragon/ref/cover.py SEED FRAMES      -> build/ddragon/cover_SEED.pkl

Virtual addresses for engine/m6809x.py: page = address >> 13 (8 KB) for the fixed slots (0-1 RAM and I/O, 4-7 the
ROM at $8000), the ROM bank at $4000-$7FFF in pages 8 + 2 * bank (slot 2) and 9 + 2 * bank (slot 3).

Seeds: 0 the attract mode only; 1-9 random play (coin, start, then the controls changing every few frames; a coin and
start again after a game over); 10-19 the same with infinite lives (DSW1 bits 6-7 = 0) so that random play goes on;
20-29 two players; -1, -2, -3 the recorded plays (tools/play_search.py: missions 2-4).  Records:
  exec     Counter of (virtual pc, slot) executed
  acc      {(virtual pc, slot): set of (r|w, address slot, virtual page, odd word start?)} data accesses
  ioacc    {(virtual pc, slot): set of (r|w, address)} accesses to $2000-$27FF (shared RAM) and $3800-$380F (I/O)
  targets  {(virtual pc, slot): set of virtual targets} of computed jumps, returns and calls
  wr_sites {(virtual pc, slot): set of areas}: the video areas a store site wrote (pal, fg, spr, bg)
  mirror   set of (virtual pc, slot) that touched the shared RAM's mirrors $2200-$27FF (all, not capped)
  dp       {(virtual pc, slot): set of DP values} of the instructions that ran with a DP other than 0
  wrap     set of (virtual pc, slot) whose indexed operand (register + constant offset) crossed $FFFF / $0000
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import DDragonPort, DSW0, DSW1
from m6809 import P1
from m6809dis import decode
from paths import build_dir


def area(a):
    if 0x1000 <= a < 0x1400:
        return "pal"
    if 0x1800 <= a < 0x2000:
        return "fg"
    if 0x2800 <= a < 0x3000:
        return "spr"
    if 0x3000 <= a < 0x3800:
        return "bg"
    return None


PALETTE_SEEDS = [11, -1, -2]              # (ref/palette_fit.py: the play it fits the colours to; -1 to mission 2, -2 to 4)
CHEATS = {}                               # seed -> [(frame, address, value)]: RAM pokes (cheats(), the tests too)


def cheats(m, seed, f):
    """the seed's RAM pokes due at frame f (before it runs) -> [(address, value)] it made"""
    out = []
    for at, a, v in CHEATS.get(seed, ()):
        if at == f or (at < 0 and f >= -at):
            m.mem[a] = v
            out.append((a, v))
    return out


def play_name(seed):
    return "play_inputs.bin" if seed == -1 else "play_inputs_%d.bin" % -seed


def play_length(seed):
    import playbot
    return len(playbot.load(build_dir("ddragon") / play_name(seed)))


def play_schedule(seed):
    """seeds -1, -2, -3: the recorded plays of tools/play_search.py (seed 1, 2, 3), as its adapter applies them"""
    import playbot
    import play_search
    ticks = playbot.load(build_dir("ddragon") / play_name(seed))

    def inputs(f):
        system, p1 = ticks[f] if f < len(ticks) else (255, 255)
        extra = 0x07
        if f >= play_search.Game.PLAY:
            if not p1 & 0x40:
                extra &= ~0x02
            p1 |= 0x40
        return p1, 0xFF, extra, 0 if system & 0x40 else 0x40
    return play_search.DSW1, inputs


def schedule(seed):
    """-> (DSW1, inputs(f) -> (P1, P2, EXTRA, coins to press)): the seed's inputs frame by frame"""
    if seed < 0:
        return play_schedule(seed)
    dsw1 = DSW1 & 0x3F if 10 <= seed < 20 else DSW1
    rng = random.Random(seed)
    play = seed > 0
    two = seed >= 20
    coin_at = 400 if play else 10 ** 9
    st = dict(hold=0, state=(0, False))

    def inputs(f):
        p1, p2, extra, coins = 0xFF, 0xFF, 0x07, 0
        if not play:
            return p1, p2, extra, coins
        k = (f - coin_at) % 3000 if f >= coin_at else -1
        if k == 0 or (two and k == 20):
            coins |= 0x40                            # coin 1 (pressed until the FIRQ takes it)
        if 100 <= k < 106:
            p1 &= ~(0x80 if two else 0x40)           # start 2 / start 1
        if k >= 150:
            if st["hold"] <= 0:
                bits = rng.choice([0, 1, 2, 4, 8, 0x10, 0x20, 0x11, 0x12, 0x21, 0x22, 0x15, 0x16, 0x01, 0x01,
                                   0x01, 0x05, 0x09, 0x30, 0x40])
                jump = rng.random() < 0.15
                st["hold"] = rng.randint(2, 30)
                st["state"] = (bits, jump)
            st["hold"] -= 1
            bits, jump = st["state"]
            if bits == 0x40:                         # (a start button now and then: continue, joining)
                p1 &= ~(0x80 if two else 0x40)
            else:
                p1 &= ~bits
                if two:
                    p2 &= ~(bits ^ 3 if bits & 3 else bits)     # (player 2 mirrored left / right)
            extra = 0x07 & ~(0x02 if jump else 0) & ~(0x04 if two and jump else 0)
        return p1, p2, extra, coins
    return dsw1, inputs


def run(seed, frames, out=None):
    m = DDragonPort(DSW0, schedule(seed)[0])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    ioacc = collections.defaultdict(set)
    targets = collections.defaultdict(set)
    wr_sites = collections.defaultdict(set)
    mirror = set()
    dps = collections.defaultdict(set)
    wraps = set()
    idx = {}                                     # (virtual pc) -> (register, offset) of a constant-offset index
    c = m.main
    accs = []

    def virt(a):
        s = a >> 13
        if s == 2 or s == 3:
            return ((8 + 2 * m.bank + s - 2) << 13) | (a & 0x1FFF)
        return a

    ord_, owr = m.port_rd, m.port_wr

    def rd(a):
        accs.append(("r", a))
        return ord_(a)

    def wr(a, v):
        accs.append(("w", a))
        owr(a, v)
    c.rd, c.wr, c.rd_op = rd, wr, rd

    def step():
        if c.attn:
            n = c._slow()
            if n:
                return n
        pc = c.pc
        key = (virt(pc), pc >> 13)
        exec_[key] += 1
        dps[key].add(c.dp)
        v = key[0]
        if v not in idx:
            ins = decode(lambda a: ord_(a & 0xFFFF) if a & 0xFFFF >= 0x4000 else m.mem[a & 0xFFFF], pc, c.dp)
            x = ins.arg if ins.mode == "idx" else None
            idx[v] = (x.reg, x.offset) if x is not None and x.kind in ("off5", "off8", "off16") and x.reg in "xyus" else None
        if idx[v] is not None:
            r, o = idx[v]
            if not 0 <= getattr(c, r) + o <= 0xFFFF:
                wraps.add(key)
        accs.clear()
        op = rd(pc)
        c.pc = (pc + 1) & 0xFFFF
        n = P1[op](c)
        c.cycles += n
        prev = None
        for rw, a in accs[1:]:
            if pc <= a < pc + 5 and rw == "r":
                continue
            oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
            acc[key].add((rw, a >> 13, virt(a) >> 13, bool(oddw)))
            if (0x2000 <= a < 0x2800 or 0x3800 <= a < 0x3810) and len(ioacc[key]) < 64:
                ioacc[key].add((rw, a))
            if 0x2200 <= a < 0x2800:
                mirror.add(key)
            if rw == "w" and area(a):
                wr_sites[key].add(area(a))
            prev = (rw, a)
        nxt = c.pc
        if not (pc < nxt <= pc + 5):
            targets[key].add(virt(nxt))
        return n
    c.step = step

    dsw1, inputs = schedule(seed)
    for f in range(frames):
        p1, p2, extra, coins = inputs(f)
        if coins:
            m.coin(coins)
        m.inputs[0], m.inputs[1], m.inputs[2] = p1, p2, extra
        cheats(m, seed, f)
        m.run_frame_port()
    data = dict(exec=exec_, acc=dict(acc), ioacc=dict(ioacc), targets=dict(targets), wr_sites=dict(wr_sites), mirror=mirror,
                dp={k: s for k, s in dps.items() if s != {0}}, wrap=wraps,
                frames=frames, seed=seed)
    out = out or build_dir("ddragon") / ("cover_%d.pkl" % seed)
    with open(out, "wb") as f:
        pickle.dump(data, f)
    return m, data


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    m, data = run(seed, frames)
    print("seed %d: %d frames, %d distinct pcs, %d MCU jobs, %d sound commands" % (
        seed, frames, len(data["exec"]), m.mcu_jobs, len(m.sound_log)))
