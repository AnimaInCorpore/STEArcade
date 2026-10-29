#!/bin/bash
# Moon Patrol in Hatari (the F030Arcade build: STE, 4 MB, TOS 2.06): a DEBUG build runs FRAMES VBLs in run/mpatrol_bench and
# writes COUNTERS.BIN and RATE.BIN (every 100 VBLs: the arcade frames and the pictures so far).
#
#   games/mpatrol/tools/bench.sh [VBLs]      default the AUTOPLAY script (a coin, start, play from the VBL);
#                                         EXTRA="-D ...": more build.py options; AVI=1: the picture recorded
#                                         (run/mpatrol_bench/mpatrol.avi) and a still every EVERY VBLs (ffmpeg); SOUND=1:
#                                         Hatari's sound on (in the AVI too: mpatrol.wav)
#
# Its own Hatari, killed by its PID only (other sessions run Hatari too).  Reports the logic (arcade frames a second;
# the arcade: 56.74) and the pictures a second separately, from the first arcade frame on.  After Mr. Do!'s (EXTRA="-D NOSOUND=1": without the sound board).
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
PY=venv/bin/python
FRAMES=${1:-6000}
BENCH=run/mpatrol_bench; mkdir -p $BENCH
$PY games/mpatrol/tools/build.py --debug -D AUTOPLAY=1 --frames $FRAMES --tag mpatrol_bench $EXTRA 2>&1 | grep -i "built\|rror" | tail -1
rm -f $BENCH/COUNTERS.BIN $BENCH/RATE.BIN $BENCH/CRASH.TXT $BENCH/mpatrol.avi $BENCH/still_*.png
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
SND=off; [ -n "$SOUND" ] && SND=44100
REC=(); [ -n "$AVI" ] && REC=(--borders true --avirecord true --avi-vcodec bmp --avi-file mpatrol.avi)
(cd $BENCH && exec "$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true \
  --sound $SND --confirm-quit off --statusbar false --fast-forward true --log-file hatari.log "${REC[@]}" MPATROL.PRG) \
  > /dev/null 2>&1 &
HP=$!
for i in $(seq ${WAIT:-900}); do sleep 1; [ -f $BENCH/COUNTERS.BIN ] || [ -f $BENCH/CRASH.TXT ] && break; kill -0 $HP 2>/dev/null || break; done
sleep 1
kill $HP 2>/dev/null; wait $HP 2>/dev/null
[ -f $BENCH/CRASH.TXT ] && { echo "--- CRASH.TXT"; head -10 $BENCH/CRASH.TXT; }
[ -f $BENCH/COUNTERS.BIN ] || { echo "no COUNTERS.BIN"; exit 1; }
python3 - <<'P'
import struct
d = open('run/mpatrol_bench/COUNTERS.BIN', 'rb').read()
v, p, i, fb, top, on, low, off = struct.unpack('>8H', d[:16])
print("VBLs %d, pictures %d, arcade frames %d" % (v, p, i))
print("borders: top armed by the VBL %d; late events: top %d, palette on %d, bottom %d, palette off %d" % (fb, top, on, low, off))
t = open('run/mpatrol_bench/RATE.BIN', 'rb').read()
pts = [struct.unpack('>2H', t[k:k + 4]) for k in range(0, len(t) - 3, 4)]
rows = [(((b[0] - a[0]) & 0xffff) / 2, ((b[1] - a[1]) & 0xffff) / 2) for a, b in zip(pts, pts[1:])]
first = next(i for i, r in enumerate(rows) if r[0])
rows = rows[first:]
print("per 100 VBLs (arcade frames/s, pictures/s):", " ".join("%d/%d" % r for r in rows))
for k, name in ((1, 'pictures'), (0, 'arcade frames')):
    s = sorted(r[k] for r in rows)
    print("%s/s over %d 2-s windows: mean %.1f, median %.1f, 10th percentile %.1f, min %.1f" % (
        name, len(s), sum(s) / len(s), s[len(s) // 2], s[len(s) // 10], s[0]))
P
if [ -n "$AVI" ] && [ -f $BENCH/mpatrol.avi ]; then
  ffmpeg -v error -i $BENCH/mpatrol.avi -vf "select=not(mod(n\,${EVERY:-300}))" -fps_mode passthrough $BENCH/still_%03d.png
  echo "stills: $(ls $BENCH/still_*.png | wc -l)"
  [ -n "$SOUND" ] && ffmpeg -v error -y -i $BENCH/mpatrol.avi -vn $BENCH/mpatrol.wav && echo "audio: $BENCH/mpatrol.wav"
fi
