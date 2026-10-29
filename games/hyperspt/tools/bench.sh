#!/bin/bash
# Speed of Hyper Sports in Hatari: a DEBUG build runs FRAMES VBLs in run/hyperspt_bench and writes COUNTERS.BIN and
# RATE.BIN (every 100 VBLs: the arcade frames and the pictures so far).
#
#   games/hyperspt/tools/bench.sh [VBLs]      PLAY=1: the recorded play (build/hyperspt/play_inputs.bin, -D PLAYBACK=1)
#                                            instead of the AUTOPLAY script; EXTRA="-D ...": more build.py options
#
# Its own Hatari (the F030Arcade build), killed by its PID only (other sessions run Hatari too).  run/hyperspt gets
# the normal build back.  Reports the logic (arcade frames a second; the arcade: 60.0) and the pictures a second
# separately, from the first arcade frame on.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python
FRAMES=${1:-6000}
BENCH=run/hyperspt_bench; mkdir -p $BENCH
MODE="-D AUTOPLAY=1"; [ -n "$PLAY" ] && MODE="-D PLAYBACK=1"
$PY games/hyperspt/tools/build.py --debug $MODE --frames $FRAMES $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
cp run/hyperspt/HYPERSPT.PRG $BENCH/HYPERSPT.PRG
$PY games/hyperspt/tools/build.py 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/RATE.BIN $BENCH/CRASH.TXT
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound off --confirm-quit off --statusbar false --fast-forward true --log-file hatari.log HYPERSPT.PRG) > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-600}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct, os
d = open('run/hyperspt_bench/COUNTERS.BIN', 'rb').read()
v, p, i, fb, top, on, low, off = struct.unpack('>8H', d[:16])
print("VBLs %d, pictures %d, arcade frames %d" % (v, p, i))
print("borders: top armed by the VBL %d; late events: top %d, palette on %d, bottom %d, palette off %d" % (fb, top, on, low, off))
t = open('run/hyperspt_bench/RATE.BIN', 'rb').read()
pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
rows = [((b[0] - a[0]) & 0xffff, (b[1] - a[1]) & 0xffff) for a, b in zip(pts, pts[1:])]
print("per 100 VBLs (arcade frames/s, pictures/s):", " ".join("%d/%d" % (a / 2, b / 2) for a, b in rows))
live = [r for r in rows if r[0]]
if live:
    f = sum(r[0] for r in live) / len(live) / 2
    print("from the first frame: logic %.1f arcade frames/s (%.0f%% of 60.0), pictures %.1f/s" % (
        f, f / 60.0 * 100, sum(r[1] for r in live) / len(live) / 2))
P
python3 - <<'P'
import struct
t = open('run/hyperspt_bench/RATE.BIN', 'rb').read()
pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
rows = [(((b[0] - a[0]) & 0xffff) / 2, ((b[1] - a[1]) & 0xffff) / 2) for a, b in zip(pts, pts[1:])]
first = next(i for i, r in enumerate(rows) if r[0])
rows = rows[first:]
for k, name in ((1, 'pictures'), (0, 'arcade frames')):
    s = sorted(r[k] for r in rows)
    print("%s/s over %d 2-s windows: mean %.1f, median %.1f, 10th percentile %.1f, min %.1f" % (
        name, len(s), sum(s) / len(s), s[len(s) // 2], s[len(s) // 10], s[0]))
P
[ -n "$PLAY" ] && python3 - <<'P'
import struct
t = open('run/hyperspt_bench/RATE.BIN', 'rb').read()
pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
rows = [(((b[0] - a[0]) & 0xffff) / 2, ((b[1] - a[1]) & 0xffff) / 2) for a, b in zip(pts, pts[1:])]
first = next(i for i, r in enumerate(rows) if r[0])
rows = rows[first + 8:]                      # (the recorded play: from tick 840, after ~14 s of attract and start)
s = sorted(r[1] for r in rows)
print("play only (%d windows): pictures/s mean %.1f, median %.1f, 10th percentile %.1f, min %.1f; arcade frames/s %.1f" % (
    len(s), sum(s) / len(s), s[len(s) // 2], s[len(s) // 10], s[0], sum(r[0] for r in rows) / len(rows)))
P
