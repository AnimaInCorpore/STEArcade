"""The native MCU model (tools/mcu.py) against the reference board's HD63701 (machine.py, port schedule).

    venv/bin/python games/galaga88/tools/mcu_test.py [frames] [--seed N] [--voice] [--commands]

The reference boots (MAME's schedule to machine.START); MCUNative takes the MCU's state from there.  Every frame: the
inputs (seed > 3: coin at 30-36, start at 130-136, random joystick and buttons after 180, now and then service and
coin 2, as logic_test.py), then the board's run_others (the MCU's window, and the sound CPU's) and MCUNative.frame on
a copy of TRIRAM as it was before the window (the sound CPU's TRIRAM writes of the window applied to it too), then
main and sub.  Compared after every window: all of TRIRAM; the MCU's RAM ($80-$EF but the loop's temporaries and,
while a sample plays, its channel's player state; without --oracle always, as the start/stop ticks are the model's);
the port 1 write.  The voice: every sample start in either
model, the tick the reference started (or stopped) it at against the model's, the end (bit 7 cleared), and the DAC and port 2 bytes
of every OCI, aligned by the start's tick offset.
--voice: voice requests poked into TRIRAM now and then (both channels, pages 3 and 6, samples 1-40)
--commands: $02F commands (1-10, 13, 14), $03C record reads and writes, $038 bits poked now and then
--oracle: the model starts and stops samples at the reference's ticks (then the DAC and port 2 bytes must be equal);
without it the DAC/port 2 frames that differ by the timing are counted, not failures
"""
import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[2] / "splatter" / "tools")]     # (the MCU model: the same program)
from machine import Galaga88
from mcu import MCUNative, TICKS

WATCH = {0xF51E: 0, 0xF5CB: 1, 0xF498: 0, 0xF545: 1}           # D6/DF switched on (start) or off (stop)
MUTE = {0xF4F3: 0, 0xF5A0: 1}                                   # D7/E0 = $80 by a start
GAIN = {0xF507: 0, 0xF5B4: 1}                                   # the gain bits by a start
TEMPS = set(range(0xC9, 0xCE)) | {0xBA, 0xBF, 0xC0, 0xC6, 0xC7}     # scratch, the bank shadow, the write times
CHANNEL = {0: set(range(0xD7, 0xDD)), 1: set(range(0xE0, 0xE5))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--commands", action="store_true")
    ap.add_argument("--oracle", action="store_true", help="the model starts/stops samples at the reference's ticks")
    args = ap.parse_args()
    m = Galaga88()
    m.boot()
    nat = MCUNative.from_board(m)
    # the board's MCU outputs of a window
    win = {"dac": [], "p1": [], "p2": [], "snd": []}
    orig_wr = m.mcu_wr

    def mcu_wr(a, v):
        if a in (0xD000, 0xD400):
            win["dac"].append((a >> 10 & 1, v))
        orig_wr(a, v)
    m.mcu.ext_wr = mcu_wr
    m.mcu.out_p[0] = lambda v, ddr: win["p1"].append(v)
    m.mcu.out_p[1] = lambda v, ddr: win["p2"].append(v)
    orig_snd = m.snd_wr

    def snd_wr(a, v):
        if 0x7000 <= a < 0x8000:
            win["snd"].append((a & 0x7FF, v))
        orig_snd(a, v)
    m.snd.wr = snd_wr

    rng = random.Random(args.seed)
    play = args.seed > 3
    hold = pulse = 0
    stats = Counter()
    offsets = Counter()
    shift = {0: 0, 1: 0}                        # reference tick - model tick of the channel's last start/stop
    nat_s, ref_s, sh_s = {0: [], 1: []}, {0: [], 1: []}, {0: [], 1: []}
    bad_frames = 0
    for f in range(args.frames):
        if play:
            if f == 30:
                m.coin_in &= ~0x10
            elif f == 36:
                m.coin_in |= 0x10
            elif f == 130:
                m.control_in[0] &= ~0x80
            elif f == 136:
                m.control_in[0] |= 0x80
            elif f > 180:
                if hold <= 0:
                    bits = rng.choice([0, 1, 2, 4, 8, 0x10, 0x20, 0x11, 0x12, 0x21, 0x22, 0x01, 0x01])
                    m.control_in[0] = (0xFF & ~bits) | 0x80
                    m.control_in[1] = 0xFF & ~(rng.choice([0, 0, 0, 0x40, 1, 2]))
                    hold = rng.randint(2, 40)
                hold -= 1
                if pulse <= 0 and rng.random() < 0.004:
                    m.coin_in = 0xF8 & ~rng.choice([0x08, 0x08, 0x40])     # coin 2 or service 1 for 4 frames
                    pulse = 4
                pulse -= 1
                if pulse == 0:
                    m.coin_in = 0xF8
        if args.voice and rng.random() < 0.03:
            ch = rng.randrange(2)
            m.triram[0x2B + 2 * ch] = rng.choice([0, rng.randrange(1, 40)])
            m.triram[0x2C + 2 * ch] = (m.triram[0x2C + 2 * ch] & 0x80) | 0x40 | rng.choice([3, 6])
        if args.commands and rng.random() < 0.02:
            poke_command(m, rng)
        before = bytearray(m.triram)
        for k in win:
            win[k] = []
        # the reference's start ticks (the OCIs before the channel is switched on), watched only when asked for
        act, mute, gain = {}, {}, {}
        if before[0x2C] & 0x40 or before[0x2E] & 0x40:
            oci = [0]

            def hook(c):
                pc = c.pc
                if pc == 0xF18C:
                    oci[0] += 1
                elif pc in WATCH:
                    act.setdefault(WATCH[pc], oci[0])
                elif pc in MUTE:
                    mute.setdefault(MUTE[pc], oci[0])
                elif pc in GAIN:
                    gain.setdefault(GAIN[pc], oci[0])
            m.mcu.hook = hook
        m.run_others()
        m.mcu.hook = None
        ntri = before
        rec = nat.frame(ntri, m.control_in[0], m.control_in[1], m.coin_in, m.dipsw, {ch: (mute.get(ch, t), gain.get(ch, t), t) for ch, t in act.items()} if args.oracle else None)
        for o, v in win["snd"]:
            ntri[o] = v
        problems = []
        # TRIRAM
        diff = [o for o in range(0x800) if ntri[o] != m.triram[o]]
        if diff:
            problems.append("TRIRAM %s" % ["%03X %02X/%02X" % (o, ntri[o], m.triram[o]) for o in diff[:8]])
        # voice starts and ends
        for k, ch, what, data in rec["events"]:
            stats[what] += 1
        ref = [[], []]
        for ch, v in win["dac"]:
            ref[ch].append(v)
        for ch in (0, 1):
            if len(ref[ch]) not in (0, TICKS):
                problems.append("reference: %d DAC writes for channel %d" % (len(ref[ch]), ch))
                continue
            if not ref[ch]:
                ref[ch] = [None] * TICKS
            got = rec["dac"][ch] or [None] * TICKS
            sh = [shift[ch]] * TICKS
            for k, c2, what, data in rec["events"]:
                if c2 == ch and what in ("started", "stopped"):
                    if ch not in act:
                        problems.append("channel %d: %s, not in the reference" % (ch, what))
                        continue
                    shift[ch] = act[ch] - k
                    offsets[(what, shift[ch])] += 1
                    lo = min(mute.get(ch, act[ch]), k)
                    for i in range(lo, TICKS):
                        sh[i] = None if i < max(act[ch], k) else shift[ch]     # (between the two: different)
            if ch in act and not any(e[1] == ch and e[2] in ("started", "stopped") for e in rec["events"]):
                problems.append("channel %d: the reference switched it at tick %d, the model did not" % (ch, act[ch]))
            nat_s[ch] += got
            ref_s[ch] += ref[ch]
            sh_s[ch] += sh
            # the previous frame's ticks: reference tick i against the model's tick i - shift
            base = len(ref_s[ch]) - 2 * TICKS
            if base >= 0:
                bad = [i for i in range(base, base + TICKS) if sh_s[ch][i] is not None and
                       0 <= i - sh_s[ch][i] < len(nat_s[ch]) and ref_s[ch][i] != nat_s[ch][i - sh_s[ch][i]]]
                if bad and not args.oracle:
                    stats["DAC frames differing by the start/stop timing"] += 1
                elif bad:
                    j = bad[0]
                    problems.append("channel %d DAC (shift %d): %d ticks of the frame before differ, first %d: %s/%s"
                                    % (ch, sh_s[ch][j], len(bad), j - base, nat_s[ch][j - sh_s[ch][j]], ref_s[ch][j]))
                else:
                    stats["DAC frames equal"] += 1
                if len(ref_s[ch]) > 4 * TICKS:      # (keep the last frames)
                    del ref_s[ch][:TICKS]
                    del nat_s[ch][:TICKS]
                    del sh_s[ch][:TICKS]
        if rec["p2"] is not None or win["p2"]:
            # (DDR2 $1D: m6801 write_port2 sends data & ddr | ~ddr, bits 0-4)
            want = [((v & 0x1D) | 0x02) & 0x1F for v in rec["p2"] or []]
            if want != win["p2"]:
                d = [k for k in range(min(len(want), len(win["p2"]))) if want[k] != win["p2"][k]]
                switched = any(e[2] in ("started", "stopped", "end") for e in rec["events"])
                if switched and not args.oracle and len(want) == len(win["p2"]):
                    stats["port 2 frames differing at a start or end (its tick)"] += 1
                else:
                    problems.append("port 2: %d writes / %d, first difference at tick %s" % (
                        len(want), len(win["p2"]), d[:1]))
        want = [(rec["p1"] & 0x87) | 0x78] if rec["p1"] is not None else []     # (DDR1 $87: the inputs read 1)
        if win["p1"] != want:
            problems.append("port 1 %s / %s" % (want, win["p1"]))
        # RAM
        busy = {ch for ch in (0, 1) if nat.ram[0xD6 if ch == 0 else 0xDF] or m.mcu.ram[(0xD6 if ch == 0 else 0xDF) - 0x80]}
        skip = set(TEMPS)
        if not args.oracle:                     # (the start/stop ticks are the model's: the player state differs)
            busy = (0, 1)
        for ch in busy:
            skip |= CHANNEL[ch] | {0xD6 if ch == 0 else 0xDF, 0xD5}
        rd = [a for a in range(0x80, 0xF0) if a not in skip and nat.ram[a] != m.mcu.ram[a - 0x80]]
        if rd:
            problems.append("RAM %s" % ["%02X %02X/%02X" % (a, nat.ram[a], m.mcu.ram[a - 0x80]) for a in rd[:8]])
            for a in rd:                         # (resync, so that one difference is reported once)
                nat.ram[a] = m.mcu.ram[a - 0x80]
        if nat.nvram != m.nvram:
            problems.append("EEPROM differs")
            nat.nvram[:] = m.nvram
        if problems:
            bad_frames += 1
            print("frame %d (%d after the start):" % (m.frame, f))
            for p in problems:
                print("   " + p)
        if not (args.voice or args.commands):   # (pokes would confuse the main CPU: then only the MCU runs)
            try:
                m.run_cpu(0)
                m.run_cpu(1)
            except RuntimeError as e:
                print("the reference's main/sub CPU (port schedule) stopped: %s; the MCU only from here" % e)
                args.voice = True
        if f % 500 == 499:
            print("%d frames, %d with differences" % (f + 1, bad_frames), flush=True)
    print("%d frames compared, %d with differences" % (args.frames, bad_frames))
    print("events:", dict(stats))
    print("reference tick - model tick of the starts/stops:", dict(sorted(offsets.items())))
    return 1 if bad_frames else 0


def poke_command(m, rng):
    t = m.triram
    k = rng.randrange(6)
    if k == 0:
        t[0x2F] = rng.choice([1, 2])
        a = rng.choice([0xC100, 0xC800 + rng.randrange(0x50), 0x0090, 0x4000 + rng.randrange(0x8000)])
        t[0x32], t[0x33] = a >> 8, a & 0xFF
    elif k == 1:
        t[0x2F] = rng.choice([3, 4])
        a = 0xC100 + rng.randrange(0x100)
        t[0x30], t[0x31], t[0x32], t[0x33] = rng.randrange(256), rng.randrange(256), a >> 8, a & 0xFF
    elif k == 2:
        t[0x2F] = rng.choice([8, 9, 10])
        t[0x31] = rng.randrange(4)
        t[0x32:0x36] = bytes([0x12, 0x34, 0x56, 0x59])
    elif k == 3:
        t[0x2F] = rng.choice([6, 7, 13])
        a = 0xC860 + rng.randrange(0x40)
        t[0x31], t[0x32], t[0x33] = rng.choice([0x5A, 0xFF]), a >> 8, a & 0xFF
        t[0x34], t[0x35], t[0x36], t[0x37] = 0xC8, 0x90 + rng.randrange(0x20), 0, rng.randrange(1, 4)
    elif k == 4:
        t[0x3C] = rng.choice([1, 2, 2])
        t[0x3D] = rng.randrange(0x10)
        for i in range(16):
            t[0x3F + i] = rng.randrange(256)
    else:
        t[0x38] = rng.randrange(8)


if __name__ == "__main__":
    sys.exit(main())
