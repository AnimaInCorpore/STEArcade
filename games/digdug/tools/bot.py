"""A player for the reference machine (tools/machine.py), for coverage and for the long runs: reads the sprite RAM (the
player is sprite 17, the Pookas and Fygars sprites 50-54), walks to the nearest enemy and pumps when it is near.  Writes the
inputs as a replay (build/digdug/bot_inputs.bin: one byte in0 and one byte in1 per frame, active low as the machine takes
them) that digdug.s plays with -D BOTPLAY, and prints what the game reached (score, rounds).

    python bot.py [frames] [--calibrate]
"""
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import DigDug, save_png, Gfx
from paths import build_dir

UP, RIGHT, DOWN, LEFT = 0x01, 0x02, 0x04, 0x08
FIRE, START, COIN = 0x01, 0x04, 0x10          # in1 bits


def spr(m, i):
    return m.ram[0x1380 + 2 * i], m.ram[0x1381 + 2 * i], m.ram[0xB80 + 2 * i], m.ram[0xB81 + 2 * i]


def decide(m, f):
    """the inputs (in0, in1: active low) of frame f: a coin and a start every 3000 frames, then the chase"""
    in0 = in1 = 0xFF
    if 800 <= f < 806 or (f >= 3000 and f % 3000 < 6):
        in1 &= ~COIN
    if 840 <= f < 846 or (f >= 3000 and 40 <= f % 3000 < 46):
        in1 &= ~START
    if f >= 1300:
        py, px, _, _ = spr(m, 17)
        best = None
        for i in range(50, 56):
            ey, ex, code, col = spr(m, i)
            if ey and col in (1, 3):
                dist = abs(ey - py) + abs(ex - px)
                if best is None or dist < best[0]:
                    best = (dist, ey, ex)
        if best is None:
            in0 &= ~(RIGHT if (f // 60) % 2 else DOWN)
        else:
            _, ey, ex = best
            dy, dx = ey - py, ex - px
            # (the sprite coordinates are rotated: RIGHT is +y, LEFT -y, DOWN +x, UP -x)
            if abs(dy) > abs(dx):
                in0 &= ~(RIGHT if dy > 0 else LEFT)
            else:
                in0 &= ~(DOWN if dx > 0 else UP)
            if abs(dy) + abs(dx) < 40 and f % 4 < 2:
                in1 &= ~FIRE
    return in0, in1


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3000
    m = DigDug(skip_tests=True, mcu_events=True)
    m.gfx = Gfx()
    out = bytearray()
    for f in range(frames):
        in0, in1 = decide(m, f)
        out += bytes([in0, in1])
        m.in0, m.in1 = in0, in1
        m.run_frame_port()
        if f % 500 == 499:
            print(f + 1, "player", spr(m, 17)[:2], "enemies", [(spr(m, i)[0], spr(m, i)[1]) for i in range(50, 56) if spr(m, i)[0] and spr(m, i)[3] in (1, 3)])
            save_png(m.render_rgb(), str(build_dir("digdug") / ("bot_%d.png" % (f + 1))))
    (build_dir("digdug") / "bot_inputs.bin").write_bytes(bytes(out))


if __name__ == "__main__":
    main()
