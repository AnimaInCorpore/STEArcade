"""Coverage of R-Type's main CPU program (V30) on the reference board (engine/m72board.py).

    venv/bin/python games/rtype/ref/cover.py SEED FRAMES      -> build/rtype/cover_SEED.pkl

Inputs (IN0 / IN1 active low): seeds 1-3 the attract mode (a coin late); 4-7 coin, start and random play (the ship
dies, the game ends, coin and start again); 8-15 the same with the Invulnerability DIP switch (SW2:7) on and the fire
button held more often: the stages go by (R-Type has no stage select).  Records, per instruction (cs, ip):
  exec      Counter of (cs, ip) executed (a REP instruction once per chunk)
  acc       {(cs, ip): set of (r|w, width 1|2, region, odd address?)} the data accesses (the instruction's own fetches
            excluded); regions: rom ram spr pal fg bg snd none
  bpar      {(cs, ip): set of the byte accesses' address parities (odd?)} (the translator's byte operands)
  addrs     {(cs, ip): set of linear addresses} for the accesses outside ROM and work RAM (at most 64 a site)
  segs      {(cs, ip): set of (DS0, DS1, SS)} the segment registers at the instruction (at most 16)
  io        {(cs, ip): set of (r|w, width, port)}
  targets   {(cs, ip): set of (cs, ip)} where the pc went when not to the next instruction (jumps, calls, returns)
  ints      Counter of ((cs, ip) of the handler, (cs, ip) interrupted)
  df        {(cs, ip): set of DF} at the string instructions
  regs      {(cs, ip): set of (AW, CW)} at the computed jumps / calls (at most 16; the table indexes)
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from m72board import M72
from v30dis import decode
from paths import build_dir

STRING_OPS = {0x6C, 0x6D, 0x6E, 0x6F, 0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF}


def region(a):
    if a < 0x40000:
        return "rom"
    if 0x40000 <= a < 0x44000:
        return "ram"
    if 0xC0000 <= a < 0xC0400:
        return "spr"
    if 0xC8000 <= a < 0xC8C00 or 0xCC000 <= a < 0xCCC00:
        return "pal"
    if 0xD0000 <= a < 0xD4000:
        return "fg"
    if 0xD8000 <= a < 0xDC000:
        return "bg"
    if 0xE0000 <= a < 0xF0000:
        return "snd"
    if a >= 0xFFFF0:
        return "rom"
    return "none"


def instrument(m):
    """hooks the board's V30 (instance attributes only): -> the record dict, filled while the board runs"""
    c = m.main.core.cpu
    rec = dict(exec=collections.Counter(), acc=collections.defaultdict(set), addrs=collections.defaultdict(set),
               segs=collections.defaultdict(set), io=collections.defaultdict(set),
               targets=collections.defaultdict(set), ints=collections.Counter(), df=collections.defaultdict(set),
               regs=collections.defaultdict(set), bpar=collections.defaultdict(set))
    accs = []
    rd, wr, wr16, io_rd, io_wr, io_wr16 = m.main_rd, m.main_wr, m.main_wr16, m.io_rd, m.io_wr, m.io_wr16
    c.rd_op = rd
    c.rd = lambda a: (accs.append(("r", 1, a)), rd(a))[1]
    c.rd16 = lambda a: (accs.append(("r", 2, a)), rd(a) | (rd((a + 1) & 0xFFFFF) << 8))[1]
    c.wr = lambda a, v: (accs.append(("w", 1, a)), wr(a, v))
    c.wr16 = lambda a, v: (accs.append(("w", 2, a)), wr16(a, v))
    c.io_rd = lambda p: (accs.append(("in", 1, p)), io_rd(p))[1]
    c.io_rd16 = lambda p: (accs.append(("in", 2, p)), io_rd(p) | (io_rd((p + 1) & 0xFFFF) << 8))[1]
    c.io_wr = lambda p, v: (accs.append(("out", 1, p)), io_wr(p, v))
    c.io_wr16 = lambda p, v: (accs.append(("out", 2, p)), io_wr16(p, v))
    ostep, ointerrupt = c.step, c.interrupt

    def interrupt(num, irq=False):
        before = (c.cs, c.ip)
        ointerrupt(num, irq)
        rec["ints"][((c.cs, c.ip), before)] += 1
    c.interrupt = interrupt

    def step():
        if c.halted:
            return ostep()
        n = c.dispatch()
        key = (c.cs, c.ip)
        cont = bool(c.rep_params)
        rec["exec"][key] += 1
        del accs[:]
        lin = (c.cs << 4) + c.ip
        op = rd(lin & 0xFFFFF)
        k = 0
        while op in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65) and k < 4:
            k += 1
            op = rd((lin + k) & 0xFFFFF)
        if op in STRING_OPS:
            rec["df"][key].add(c.df)
        if op == 0xFF:
            sub = (rd((lin + k + 1) & 0xFFFFF) >> 3) & 7
            if sub in (2, 3, 4, 5) and len(rec["regs"][key]) < 16:
                rec["regs"][key].add((c.aw, c.cw))
        s = rec["segs"][key]
        if len(s) < 16:
            s.add((c.ds, c.es, c.ss))
        n += ostep()
        for rw, w, a in accs:
            if rw in ("in", "out"):
                rec["io"][key].add((rw, w, a & 0xFFFF))
                continue
            reg = region(a)
            rec["acc"][key].add((rw, w, reg, bool(a & 1) and w == 2))
            if w == 1:
                rec["bpar"][key].add(bool(a & 1))
            if reg not in ("rom", "ram"):
                ad = rec["addrs"][key]
                if len(ad) < 64:
                    ad.add(a)
        nxt = (c.cs, c.ip)
        if not c.rep_params and nxt != key:
            ln = decode_len(rd, lin)
            if nxt != (key[0], (key[1] + ln) & 0xFFFF):
                rec["targets"][key].add(nxt)
        return n
    c.step = step
    return rec


def decode_len(rd, lin):
    return decode(rd, lin).length


def finish(rec):
    return {k: (dict(v) if isinstance(v, collections.defaultdict) else v) for k, v in rec.items()}


def press(m, f, seed, rng, state):
    """the inputs of frame f (IN0 low byte: right 1 left 2 down 4 up 8, button 2 $40 (the Force), button 1 $80 (fire);
    IN1: start 1 bit 0, coin 1 bit 2)"""
    play = seed > 3
    coin_at = 400 if play else 3000
    in1 = 0xFFFF
    if f % 2400 in (coin_at, coin_at + 1, coin_at + 2, coin_at + 3) or (f == coin_at):
        in1 &= ~0x04
    if play and f % 2400 in range(coin_at + 60, coin_at + 66):
        in1 &= ~0x01
    m.in1 = in1
    if not play or f < coin_at + 120:
        m.in0 = 0xFFFF
        return
    if state["hold"] <= 0:
        bits = rng.choice([0, 1, 2, 4, 8, 5, 9, 6, 10, 0x80, 0x81, 0x82, 0x84, 0x88, 0x40, 0x01, 0x01, 0x80])
        if seed >= 8 and rng.random() < 0.6:
            bits |= 0x80
        state["bits"] = bits
        state["hold"] = rng.randint(2, 60)
    state["hold"] -= 1
    bits = state["bits"]
    if seed >= 8 and bits & 0x80 and f % 90 == 0:
        bits &= ~0x80                                   # (release now and then: a charged shot)
    m.in0 = 0xFFFF & ~bits


def run(seed, frames, out=None):
    m = M72("rtype")
    if seed >= 8:
        m.dsw &= ~0x4000                                # Invulnerability
    rec = instrument(m)
    rng = random.Random(seed)
    state = dict(hold=0, bits=0)
    for f in range(frames):
        press(m, f, seed, rng, state)
        m.run_frame()
    data = finish(rec)
    data.update(frames=frames, seed=seed)
    out = out or build_dir("rtype") / ("cover_%d.pkl" % seed)
    with open(out, "wb") as fh:
        pickle.dump(data, fh)
    return m, data


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    m, data = run(seed, frames)
    print("seed %d: %d frames, %d distinct (cs, ip)" % (seed, frames, len(data["exec"])))
