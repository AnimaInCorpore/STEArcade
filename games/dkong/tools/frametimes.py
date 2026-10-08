"""How long the frames took: python frametimes.py TIMES.BIN

A build with -D TIMES=1 -D DEBUG=1 --frames N starts MFP Timer D at every VBL (256 ticks
of 81.4 us, i.e. 652.8 CPU cycles) and records its count when the Z80 NMI and when the
frame's drawing are done, with the skipped-VBL count; it writes the records to TIMES.BIN
when it quits.  A frame during which a VBL was skipped ran into the next frame.
"""
import sys
from collections import Counter

TICK = 652.8                # CPU cycles per Timer D tick (prescaler 200)
FRAME = 160256              # CPU cycles per 50 Hz frame
FRAME_TICKS = FRAME / TICK  # 245.5

d = open(sys.argv[1], "rb").read()
recs = [d[i:i + 4] for i in range(0, len(d) - 3, 4)]
nmi, ticks, banks = [], [], []
last_skip = recs[0][2]
for t_nmi, t_end, skip, bank in recs:
    banks.append(bank)
    a = (256 - t_nmi) & 0xFF
    b = (256 - t_end) & 0xFF
    over = (skip - last_skip) & 0xFF
    last_skip = skip
    if over:
        b += over * 256           # the timer wrapped (once per 20.8 ms)
        if a > b:
            a += 256
    nmi.append(a)
    ticks.append(b)

n = len(ticks)
pct = lambda t: 100.0 * t / FRAME_TICKS
late = sum(1 for t in ticks if t >= FRAME_TICKS)
print("%d frames, %d (%.1f%%) ran into the next VBL" % (n, late, 100.0 * late / n))
print("average %.0f%% of a frame (Z80 NMI %.0f%%, drawing %.0f%%), max %.0f%% (NMI max %.0f%%, drawing max %.0f%%)" % (
    pct(sum(ticks) / n), pct(sum(nmi) / n), pct(sum(t - a for t, a in zip(ticks, nmi)) / n),
    pct(max(ticks)), pct(max(nmi)), pct(max(t - a for t, a in zip(ticks, nmi)))))
print("frame time, percent of a frame:")
hist = Counter(min(int(pct(t)) // 10 * 10, 200) for t in ticks)
for b in sorted(hist):
    bar = "#" * (hist[b] * 60 // n + (1 if hist[b] else 0))
    label = "%3d-%3d%%" % (b, b + 9) if b < 200 else "   200%+"
    print("  %s %5d %s" % (label, hist[b], bar))
worst = sorted(range(n), key=lambda i: -ticks[i])[:12]
print("longest frames (index: total = NMI + drawing, percent; bank):")
print("  " + ", ".join("%d: %.0f = %.0f + %.0f; %d" % (i, pct(ticks[i]), pct(nmi[i]), pct(ticks[i] - nmi[i]), banks[i]) for i in worst))
changes = sum(1 for i in range(1, n) if banks[i] != banks[i - 1])
print("palette bank changes (every tile drawn again): %d" % changes)
