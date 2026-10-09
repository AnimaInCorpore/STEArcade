#!/bin/bash
# Speed of 1942 in Hatari: a DEBUG + AUTOPLAY build (scripted coin, start, fire and joystick, MAME's cheats for 1942b: lives, invincibility
# and, with a period, "Finish Current Level Now!" to reach the later stages) runs 6000 VBLs and writes COUNTERS.BIN.
#
#   games/1942/tools/bench.sh [finish_period] [hatari items ...]      finish_period: frames between level skips, 0 = none (default)
#   EXTRA="-D NOTICK60=1" games/1942/tools/bench.sh 600 shot@70      extra build.py options;  WAIT=140: seconds before Hatari is stopped
#
# Reports the game ticks a second (the arcade: 59.6), the frames drawn a second, a histogram of the VBLs between two ticks and the
# time the CPU idled.  The first 300 VBLs are the boot (no ticks): 95% of 59.6 is full speed.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT"
FIN=${1:-0}; shift
PY=venv/bin/python; [ -x $PY ] || PY=python3
$PY games/1942/tools/build.py -D DEBUG=1 -D AUTOPLAY=1 $( [ "$FIN" != 0 ] && echo -D FINISH=$FIN ) --frames 6000 $EXTRA 2>&1 | grep -v translated | tail -2
rm -f run/1942/COUNTERS.BIN
tools/hatari.sh 1942 "$@" wait@${WAIT:-128} > /tmp/bench.out 2>&1
python3 - <<'P'
import struct
d = open('run/1942/COUNTERS.BIN', 'rb').read()
v, h, r, b, i = struct.unpack('>5H', d[:10]); hist = struct.unpack('>10H', d[10:30])
ib, idf, pieced = struct.unpack('>3I', d[30:42]); bd = struct.unpack('>5H', d[42:52])
print("VBLs between two ticks, 0..9+:", hist)
print("idle spins: no free ring", ib, "nothing to do", idf, "; Blitter passes run in pieces", pieced)
print("borders: top border armed by the VBL in %d frames; events that started too late: top border %d, palette on %d, bottom border %d, palette off %d" % bd)
print("VBLs", v, "frames drawn", r, "ticks", i)
print("game ticks %.1f /s (arcade 59.6) = %.0f%% speed;  frames drawn %.1f /s" % (i / v * 50, i / v * 50 / 59.6 * 100, r / v * 50))
P
