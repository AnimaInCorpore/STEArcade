#!/bin/bash
# Records Hatari's picture as an AVI (PNG frames; every state is repeated, the emulation runs slower while recording) to look at
# frames one by one:   games/1942/tools/record.sh [out.avi] [start_s] [length_s]   then   ffmpeg -i out.avi frames/f%04d.png
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HATARI=${HATARI:-/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari}
TOS=${TOS:-/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img}
OUT=${1:-/tmp/hrun/rec.avi}; S=${2:-20}; L=${3:-8}
mkdir -p /tmp/hrun; rm -f "$OUT" /tmp/hrun/cmd.fifo
pkill -x hatari 2>/dev/null; sleep 1
cd "$ROOT/run/1942"
"$HATARI" --machine ste --memsize 4 --tos "$TOS" --fast-boot true --cpu-exact true --compatible true --sound off --confirm-quit off \
  --cmd-fifo /tmp/hrun/cmd.fifo --avi-vcodec png --avi-file "$OUT" --avi-fps 50 1942.PRG > /tmp/hrun/rec.log 2>&1 &
HP=$!
for i in $(seq 50); do [ -p /tmp/hrun/cmd.fifo ] && break; sleep 0.2; done
sleep $S;  echo "hatari-shortcut recanim" > /tmp/hrun/cmd.fifo
sleep $L;  echo "hatari-shortcut recanim" > /tmp/hrun/cmd.fifo
sleep 1; kill $HP
