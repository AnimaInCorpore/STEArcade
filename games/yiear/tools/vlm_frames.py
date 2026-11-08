"""How long the VLM5030's BSY stays high after a phrase starts, in arcade frames: the reference's port schedule and the
STE runtime have no time between frames, so both take this table (indexed by the data byte the game latches before ST
falls; the speech parameter is 0, as the game's sequence RST 1, data 0, RST 0 sets it).

    frames() -> 256 ints (cached in build/yiear/vlm_frames.json)
"""
import json
import math
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import build_dir
from vlm5030 import phrase, RATE

FRAME_HZ = 18432000 / 3 / (384 * 264)               # 60.606 Hz
SAMPLES_PER_FRAME = RATE / FRAME_HZ                 # 134.2


def frames():
    cache = build_dir("yiear") / "vlm_frames.json"
    if cache.exists():
        return json.loads(cache.read_text())
    from machine import load
    rom = load("407_c09.8b")
    out = []
    for data in range(256):
        _, n = phrase(rom, data, 0, limit=400000)
        out.append(max(1, min(255, math.ceil(n / SAMPLES_PER_FRAME))))
    cache.write_text(json.dumps(out))
    return out


if __name__ == "__main__":
    f = frames()
    print(f[:32], max(f))
