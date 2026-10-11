"""1943's sound on the STE's YM2149: the sound driver (Capcom's, as Commando's and Gun.Smoke's) recorded per command
by engine/capsnd.py, played by engine/rt/capsnd.s.

The board (MAME capcom/1943.cpp): a Z80 at 3 MHz, ROM 0000-7FFF, RAM C000-C7FF, the latch at C800 (the main CPU's
C800), two YM2203 at E000-E003 (1.5 MHz), four IRQs a frame (lines 32, 96, 160, 224); D800 (the MCU's port) is not
used by the driver.  The driver: IRQ 0038 counts in C000, reads the latch (008D: the table at 009F), steps the music
(021A: slots C100-C400), sequences (05B7) and outputs (0A25) the effects: five slots a chip (C500-C580, C600-C680); the
output ends the lower slots under the one shown unless their byte 31 is $FF (0A8E / 0C4B), which an effect opcode
sets (075D).  Command 00 clears the effects (0125) and stops the music (0140); 33-39 and 3B-3F stop the music.

    python sound.py record          record the effects and the tunes again (build/1943/fx.pkl, music.pkl)
    python sound.py check [ticks]   the STE player's model against the driver: random commands, then the game's own
    python sound.py emit            build/1943/cs_data.s
    python sound.py wav XX [ticks]  command $XX through the STE player as build/1943/sound_XX.wav (to listen)
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import capsnd
from paths import build_dir


def driver():
    b = build_dir("1943")
    return capsnd.Driver("1943", (b / "audiocpu.rom").read_bytes(), (0xC000, 0x800), 0xC800, 0xE000, (0x007C, 0x007D),
                         0xC000, 0xC001, 0x009F, [[0xC500 + 0x20 * i for i in range(5)], [0xC600 + 0x20 * i for i in range(5)]],
                         [0xC100, 0xC200, 0xC300, 0xC400], kill=31, irq_lines=(32, 96, 160, 224), build=b)


def game_latches(ticks):
    """the latch at each tick of the reference in the port's schedule (logic_test.py's play): what cs_tick reads"""
    from machine import Game1943
    from logic_test import inputs
    m = Game1943()
    out = []
    for f in range(ticks):
        out.append(m.sound_latch if f else 0xFF)
        m.inputs[:3] = inputs(f)
        m.run_frame_port()
    return out


def check(ticks):
    d = driver()
    bad = capsnd.mus_check(d)
    print("random commands:")
    bad += capsnd.fx_check(d, capsnd.random_latches(d, ticks))
    print("the game (logic_test.py's play):")
    seq = game_latches(ticks)
    print("  %d commands: %s" % (sum(1 for a, b in zip(seq, seq[1:]) if b != a and b != 0xFF),
                                 " ".join("%02X" % c for c in sorted(set(seq)))))
    bad += capsnd.fx_check(d, seq)
    return bad


if __name__ == "__main__":
    d = driver()
    if sys.argv[1:2] == ["record"]:
        capsnd.all_effects(d, again=True)
        capsnd.all_tunes(d, again=True)
        sys.exit(1 if capsnd.mus_check(d) else 0)
    if sys.argv[1:2] == ["check"]:
        sys.exit(1 if check(int(sys.argv[2]) if len(sys.argv) > 2 else 6000) else 0)
    if sys.argv[1:2] == ["emit"]:
        print("cs_data.s: %d bytes" % capsnd.emit(d, build_dir("1943") / "cs_data.s"))
    if sys.argv[1:2] == ["wav"]:
        cmd = int(sys.argv[2], 16)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3600
        ste = capsnd.Ste(d)
        path = build_dir("1943") / ("sound_%02X.wav" % cmd)
        capsnd.wav(path, [ste.tick(cmd if i < 2 else 0xFF) for i in range(n)], d.fps)
        print(path)
