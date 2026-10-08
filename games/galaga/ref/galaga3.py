"""Galaga reference statistics for the port: sprites changed per frame, tiles changed per
frame, I/O accesses by instruction, spin loops.  python ref/galaga3.py [frames]"""
import os, sys
from collections import Counter, defaultdict
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Galaga
from z80dis import decode

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
m = Galaga()
io = defaultdict(Counter)        # (cpu, kind) -> Counter of (pc, addr range)
spin = [defaultdict(int) for _ in range(3)]      # pc of a taken backward jump -> max run
run = [[None, 0] for _ in range(3)]
for n in range(3):
    cpu = m.cpus[n]
    rom = m.roms[n]
    rd, wr = cpu.rd8, cpu.wr8

    def hook_rd(a, n=n, cpu=cpu, rd=rd):
        if 0x6800 <= a < 0x8000 or a >= 0xa000 or 0x8c00 <= a < 0x9000 or 0x9400 <= a < 0x9800 or 0x9c00 <= a:
            io[(n, "r")][(cpu.pc, a & 0xff00)] += 1
        return rd(a)

    def hook_wr(a, v, n=n, cpu=cpu, wr=wr):
        if 0x6800 <= a < 0x8000 or a >= 0xa000 or 0x8c00 <= a < 0x9000 or 0x9400 <= a < 0x9800 or 0x9c00 <= a:
            io[(n, "w")][(cpu.pc, a & 0xff00)] += 1
        wr(a, v)
    cpu.rd8, cpu.wr8 = hook_rd, hook_wr


def script(m, f):
    m.in0 = m.in1 = 0xff
    if 1500 <= f < 1506: m.in1 &= ~0x10
    if 1540 <= f < 1546: m.in1 &= ~0x04
    if f >= 1560:
        g = f - 1560
        if (g // 40) % 2: m.in0 &= ~0x02
        else: m.in0 &= ~0x08
        if g % 20 < 3: m.in1 &= ~0x01


def sprite_table(ram):
    return [bytes((ram[0xb80 + o], ram[0xb81 + o], ram[0x1380 + o], ram[0x1381 + o], ram[0x1b80 + o], ram[0x1b81 + o]))
            for o in range(0, 0x80, 2)]


prev_spr = sprite_table(m.ram)
prev_vram = bytes(m.ram[:0x800])
changed_hist = Counter()
tiles_hist = Counter()
active_hist = Counter()
sizes = Counter()
pcs_seen = [set(), set(), set()]
for f in range(frames):
    script(m, f)
    # spin detection: sample pcs each instruction is too slow; sample per frame the idle pc
    m.run_frame()
    for n in range(3):
        pcs_seen[n].add(m.cpus[n].pc)
    spr = sprite_table(m.ram)
    if f >= 800:
        act = [s for s in spr if s[0] != 0 or s[1] != 0]
        changed = sum(1 for a, b in zip(spr, prev_spr) if a != b and (a[0] | a[1]))
        changed_hist[changed] += 1
        active_hist[sum(1 for s in spr if (s[2] - 40 + 256 * (s[5] & 3)) < 288 and s[0] | s[1])] += 1
        for s in spr:
            sizes[(s[4] >> 2) & 3] += 1
        vram = bytes(m.ram[:0x800])
        tiles_hist[sum(1 for i in range(0x400) if vram[i] != prev_vram[i] or vram[i + 0x400] != prev_vram[i + 0x400])] += 1
        prev_vram = vram
    prev_spr = spr
print("frames", frames)
tot = sum(changed_hist.values())
print("sprites changed per frame: mean %.1f, max %d, 90%% %d" % (
    sum(k * v for k, v in changed_hist.items()) / tot, max(changed_hist),
    sorted(k for k, v in changed_hist.items() for _ in range(v))[int(tot * 0.9)]))
print("sprites on screen per frame: mean %.1f, max %d" % (sum(k * v for k, v in active_hist.items()) / tot, max(active_hist)))
print("sprite sizes (0: 16x16, 1: 32x16, 2: 16x32, 3: 32x32):", dict(sizes))
print("tiles changed per frame: mean %.1f, max %d" % (sum(k * v for k, v in tiles_hist.items()) / tot, max(tiles_hist)))
for key in sorted(io):
    n, kind = key
    rom = m.roms[n]
    print("CPU%d %s:" % (n + 1, "reads" if kind == "r" else "writes"))
    for (pc, page), c in sorted(io[key].items()):
        ins = decode(rom, pc) if pc < len(rom) else None
        print("   %04X %-18s %04Xxx %d" % (pc, ins.text if ins else "?", page, c))
for n in range(3):
    print("CPU%d pcs at frame ends:" % (n + 1), ", ".join("%04X" % p for p in sorted(pcs_seen[n])[:30]), "(%d)" % len(pcs_seen[n]))
