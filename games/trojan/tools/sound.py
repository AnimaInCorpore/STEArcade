"""Trojan's sound on the STE's YM2149: the sound driver (Capcom's, the Commando / Gun.Smoke family) recorded per command
by engine/capsnd.py, played by engine/rt/capsnd.s.  The ADPCM voices (the second Z80 and its MSM5205) are not played.

The board (MAME capcom/lwings.cpp, the trojan machine): a Z80 at 3 MHz, ROM 0000-7FFF (tb_02.15h), RAM C000-C7FF, the
latch at C800 (the main CPU's F80C), two YM2203 at E000-E003 (1.5 MHz), an IRQ at lines 32, 96, 160, 224 of the 282.
The driver is Gun.Smoke's at other addresses: IRQ 0038 counts in C000, reads the latch (0073: `and $7F`, the rst 30
table at 0085: 128 commands), steps the music (0306: slots C100-C400), sequences (0642) and outputs (0B38) the effects:
five slots a chip (C500-C580, C600-C680); the output ends the lower slots under the one shown unless their byte 31 is
$FF (0BA5 / 0CE2), which an effect opcode sets (07DA).  Commands 01-2E are effects, 30-47 tunes, 00 / 2F clear the
effect slots, 48-4F stop the music.

    python sound.py record          record the effects and the tunes again (build/trojan/fx.pkl, music.pkl)
    python sound.py check [frames]  the STE player's model against the driver: random commands, then the game's own
    python sound.py emit            build/trojan/cs_data.s
    python sound.py wav XX [ticks]  command $XX through the STE player as build/trojan/sound_XX.wav (to listen)
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref")]
import capsnd
from paths import build_dir
from machine import load


def driver():
    b = build_dir("trojan")
    rom = load("tb02.bin")
    return capsnd.Driver("trojan", rom + bytes([0xFF]) * (0x10000 - len(rom)), (0xC000, 0x800), 0xC800, 0xE000,
                         (0x0070, 0x0071), 0xC000, 0xC001, 0x0085,
                         [[0xC500 + 0x20 * i for i in range(5)], [0xC600 + 0x20 * i for i in range(5)]],
                         [0xC100, 0xC200, 0xC300, 0xC400], kill=31, irq_lines=(32, 96, 160, 224), lines=282,
                         build=b, mask=0x7F)


def game_latches(frames, seed=0):
    """the latch at each arcade frame of the reference in the port's schedule (ref/cover.py's inputs): what cs_tick
    reads"""
    from machine import TrojanPort
    import cover
    level, cheats, inputs = cover.schedule(seed)
    m = TrojanPort()
    m.run_to_idle()
    m.booted = True
    out = []
    for f in range(frames):
        out.append(m.mem[0xF80C] if f else 0xFF)
        m.inputs[0], m.inputs[1] = inputs(f)
        if seed == 0 and f % 3000 >= 1000:
            m.mem[0xCDA0] = 3
        m.run_frame_port()
    return out


def check(frames):
    d = driver()
    bad = capsnd.mus_check(d)
    print("random commands:")
    bad += capsnd.fx_check(d, capsnd.random_latches(d, frames))
    print("the game (the AUTOPLAY schedule):")
    seq = game_latches(frames)
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
        print("cs_data.s: %d bytes" % capsnd.emit(d, build_dir("trojan") / "cs_data.s"))
    if sys.argv[1:2] == ["wav"]:
        cmd = int(sys.argv[2], 16)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3600
        ste = capsnd.Ste(d)
        path = build_dir("trojan") / ("sound_%02X.wav" % cmd)
        capsnd.wav(path, [ste.tick(cmd if i < 2 else 0xFF) for i in range(n)], d.fps)
        print(path)
