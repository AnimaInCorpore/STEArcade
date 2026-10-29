"""Gauntlet's sound on the STE, checked three ways (tools/sound.py has the recordings, the data and the Python model of
src/sound_out.s):

    venv/bin/python games/gauntlet/tools/sound_test.py [player] [driver] [mame] [hatari] [--ticks N]

  player  src/sound_out.s (assembled with a small harness, -DSIM, on engine/sim.py's Musashi) against tools/sound.py's
          Player, tick by tick: the YM2149's registers 0-10, the phrase started (the DMA's start and end) and the
          speech samples decoded (ADPCM) after every snd_out_vbl, for every sound and phrase alone, scenarios of priorities, fades, stops and the speech
          queue, and the game's own command streams (ref/cover.py's runs on the STE's schedule: the attract mode,
          one player, three players; a game frame a tick).  Also the cycles snd_out_vbl takes.
  driver  the model against the real driver: the reference board's 6502 (tools/sound.py RecBoard) fed the game's
          command streams at the same ticks, its chips' output per logical channel (tools/sound.py chip_ticks) against
          the Player's channels before the mixer (equal; alike: the same mode, volumes within 1, periods within 3 %;
          alike a tick off: the driver updates at 240 Hz, its changes land a tick early or late against the 50 Hz
          ticks); the phrases' starts against the driver's ($2B = $80).
  mame    pitches against MAME 0.289's audio: a script pokes commands into the sound latch in a quiet stretch of the
          attract mode (-wavwrite); the Player's YM2149 output for the same commands rendered as square waves; their
          semitone spectra per piece correlated (at the right octave and shifted by +-1 semitone and +-12); the
          speech's waveform against MAME's.  Writes build/gauntlet/sound_mame.wav and sound_ste.wav to listen to.
  hatari  the player on the STE: a small program (build/gauntlet/sndhw/) calls snd_out_vbl from the VBL with a script
          of commands, in its own Hatari (STE, sound on; HATARI= / TOS= as tools/shots.sh), its audio recorded; the
          pieces' semitone spectra and the phrase's waveform (the DMA sound) against the Player's
"""
import math
import os
import pickle
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parent), str(HERE.parents[3] / "engine")]
import mamewin                       # (MAME runs minimized)
import numpy as np
import sound as S
from paths import ROOT, build_dir, VASM, VLINK

BUILD = build_dir("gauntlet")
MAME_HZ = 59.922743                      # the arcade's frame rate (machine.py FRAME_AS)


# ================================================================================================= the 68000 player

HARNESS = """; sound_test.py's harness for src/sound_out.s (SIM)
	section text,code
	jsr	sim_wait
sim_wait:
	bra.s	sim_wait
	include	"sound_out.s"
	section bss,bss
	even
snd_queue:	ds.b	64
snd_qhead:	ds.b	1
	even
"""


def build_harness():
    src = HERE.parents[1] / "src"
    (BUILD / "sound_test.s").write_text(HARNESS)
    obj = BUILD / "sound_test.o"
    prg = BUILD / "SNDTEST.PRG"
    mp = BUILD / "sound_test.map"
    for cmd in ([VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(src), "-I", str(BUILD), "-o", str(obj),
                 str(BUILD / "sound_test.s")],                      # (the STE build assembles too)
                [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-DSIM=1", "-I", str(src), "-I", str(BUILD), "-o", str(obj),
                 str(BUILD / "sound_test.s")],
                [VLINK, "-b", "ataritos", "-M" + str(mp), "-o", str(prg), str(obj)]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg, mp


class Ste:
    """the assembled player on Musashi"""

    def __init__(self):
        from sim import Sim
        prg, mp = build_harness()
        self.sim = Sim(str(prg), run_dir=BUILD)
        self.sim.mem.set_trace_mode(False)
        self.sym = {k: v + self.sim.base for k, v in self.sim.symbols(mp).items()}
        self.mem, self.cpu = self.sim.mem, self.sim.cpu
        from machine68k import Register
        self.R = Register
        self.stop = self.sym["sim_wait"]
        while self.cpu.r_pc() != self.stop:
            self.cpu.execute(2000)
        self.call("snd_out_init")
        self.head = self.mem.r8(self.sym["snd_qhead"])

    def call(self, label):
        cpu, mem = self.cpu, self.mem
        sp = cpu.r_reg(self.R.A7) - 4
        mem.w32(sp, self.stop)
        cpu.w_reg(self.R.A7, sp)
        cpu.w_pc(self.sym[label])
        cycles = 0
        while cpu.r_pc() != self.stop:
            cycles += cpu.execute(40).cycles
        return cycles

    def tick(self, cmds=()):
        for c in cmds:
            self.mem.w8(self.sym["snd_queue"] + self.head, c)
            self.head = (self.head + 1) & 63
        self.mem.w8(self.sym["snd_qhead"], self.head)
        cyc = self.call("snd_out_vbl")
        regs = [self.mem.r8(self.sym["so_regs"] + i) for i in range(11)]
        sp = self.mem.r16(self.sym["so_speech"])
        buf = self.sym["so_spbuf"]
        dma = (self.mem.r32(self.sym["so_dma_start"]) - buf, self.mem.r32(self.sym["so_dma_end"]) - buf)
        dec = self.mem.r32(self.sym["so_dout"]) - buf
        return regs, (None if sp == 0xFFFF else sp), dma, dec, cyc

    def decoded(self, a, b):
        return list(self.mem.r_block(self.sym["so_spbuf"] + a, b - a))


def scenarios():
    """[(name, [commands a tick])]"""
    out = []
    for s in range(S.SOUNDS):
        c = S.sound_command(s)
        n = 400 if s in (0x37,) else 300
        out.append(("sound %02X" % s, [[0, c]] + [[]] * n))
    for p in range(S.PHRASES):
        out.append(("phrase %02X" % p, [[0, S.phrase_command(p)]] + [[]] * 40))
    sc = [[0, 0x42]] + [[]] * 100 + [[0x1A]] + [[]] * 50 + [[0x0D, 0x11]] + [[]] * 60 + [[0x43]] + [[]] * 200
    out.append(("music, effects over it, fade", sc))
    sc = [[0x44]] + [[]] * 60 + [[0x0D]] + [[]] * 30 + [[0x48]] + [[]] * 200 + [[0x2F]] + [[]] * 50 + [[0x30]] + [[]] * 20
    out.append(("tune, same priority, fade by priority, stop a sound", sc))
    sc = [[0x5A], [0x5B], [0x5C], [0x51, 0x52]] + [[]] * 300 + [[0x01], [0x5A]] + [[]] * 20 + [[0x02, 0x5D]] + [[]] * 20
    out.append(("speech queue, floor", sc))
    sc = [[c] for c in range(0x09, 0x51)] + [[]] * 100 + [[0x00]] + [[]] * 20
    out.append(("every sound a tick, stop all", sc))
    sc = [[0xDD], [0x4A]] + [[]] * 30 + [[0xE0], [0x4A, 0x5E]] + [[]] * 100
    out.append(("mixer, ducking", sc))
    return out


def game_streams(ticks=None):
    """[(name, [commands a tick])]: ref/cover.py's runs (the STE's schedule), a game frame a tick, without the
    sound-board queries ($03, $07)"""
    out = []
    for seed, name in ((0, "attract"), (1, "1 player"), (12, "3 players")):
        d = pickle.loads((BUILD / ("cover_%d.pkl" % seed)).read_bytes())
        n = ticks or (max(f for f, v in d["sound"]) + 1)
        sc = [[] for _ in range(n)]
        for f, v in d["sound"]:
            if f < n and v not in (3, 7):
                sc[f].append(v)
        out.append((name, sc))
    return out


def test_player(enc, ticks=None):
    ste = Ste()
    bad_all = total = 0
    cyc_max = cyc_sum = calls = 0
    for name, sc in scenarios() + game_streams(ticks):
        ste.tick([0x00])                         # (everything stopped between scenarios: in both)
        ste.tick([])
        model = S.Player(enc)
        model.slots = [None] * S.NSLOT
        # the model starts where the player is: the same stop, then the scenario
        model = sync_model(enc, ste)
        bad = 0
        cycs = []
        for k, cmds in enumerate(sc):
            n0 = len(model.dec_out)
            regs, sp, dma, dec, cyc = ste.tick(cmds)
            cycs.append(cyc)
            want = model.tick(cmds)
            wsp = model.speech
            total += 1
            calls += 1
            cyc_sum += cyc
            cyc_max = max(cyc_max, cyc)
            ok = regs == want and sp == wsp
            if ok and sp is not None:
                ok = dma == (0, 2 * enc["phrases"][sp][0])
            if ok and model.dec_out:                 # the samples decoded this tick
                if sp is not None:
                    n0 = 0
                ok = dec == len(model.dec_out) and ste.decoded(n0, dec) == model.dec_out[n0:]
            if not ok:
                bad += 1
                if bad <= 3:
                    print("  %s tick %d: player %s %s, model %s %s" % (name, k, regs, sp, want, wsp))
        bad_all += bad
        if bad or name.startswith(("attract", "1 player", "3 players", "music", "tune", "speech", "every", "mixer")):
            cycs.sort()
            print("%-52s %6d ticks, %d differ; cycles: median %d, 99 %% %d, max %d" % (
                name, len(sc), bad, cycs[len(cycs) // 2], cycs[len(cycs) * 99 // 100], cycs[-1]))
    print("player: %d ticks, %d differ; snd_out_vbl %d cycles on average, %d at most" % (
        total, bad_all, cyc_sum // max(1, calls), cyc_max))
    return bad_all == 0


def sync_model(enc, ste):
    """a model in the player's state after its init and the stops (no voices, no speech queue): a fresh one whose
    tail state (the mixer, floor, speech counters) is read back from the player"""
    m = S.Player(enc)
    mem, sym = ste.mem, ste.sym
    m.regs = [mem.r8(sym["so_regs"] + i) for i in range(11)]
    m.assigned = [x if x < 128 else -1 for x in (mem.r8(sym["so_assigned"] + i) for i in range(12))]
    m.floor = mem.r8(sym["so_floor"])
    m.mixer = mem.r8(sym["so_mixer"])
    m.busy = mem.r16(sym["so_busy"])
    m.duck = mem.r16(sym["so_duck"])
    m.duck_mix = mem.r8(sym["so_duckmix"])
    m.cur_pri = mem.r8(sym["so_curpri"])
    m.qhead = mem.r8(sym["so_qhead"])
    m.qtail = mem.r8(sym["so_qtail"])
    m.queue = [mem.r8(sym["so_queue"] + i) for i in range(8)]
    return m


# ================================================================================================= the real driver

def close(a, b):
    """two channel values sound alike: both silent, or the same mode, volumes within 1, periods within 3 %"""
    if not a[3] and not b[3]:
        return True
    if not a[3] or not b[3]:
        return max(a[3], b[3]) <= 2
    if a[2] != b[2] or abs(a[3] - b[3]) > 1:
        return False
    if a[2] & 1 and abs(a[0] - b[0]) > 0.03 * max(a[0], b[0]):
        return False
    if a[2] & 2 and abs(a[1] - b[1]) > 1:
        return False
    return True


def test_driver(enc, ticks=3000):
    ok = True
    for name, sc in game_streams(ticks):
        b = S.RecBoard()
        cmds = [(k, c) for k, cs in enumerate(sc) for c in cs]
        t = time.time()
        r = S.record_raw(cmds, len(sc), quiet=0, board=b, stop_first=False)
        rows = S.chip_ticks(b.snd_devices.log, r["t0"], len(sc))
        model = S.Player(enc)
        exact = near = shifted = n = 0
        per_ch = [0] * S.CHANNELS
        sp_model, sp_ref = [], []
        for k, cs in enumerate(sc):
            model.tick(cs)
            if model.speech is not None:
                sp_model.append(k)
            for c in range(S.CHANNELS):
                a, m_ = rows[k][c], model.chans[c]
                if not a[3] and not m_[3]:
                    continue
                n += 1
                if a == m_:
                    exact += 1
                elif close(a, m_):
                    near += 1
                elif any(close(rows[j][c], m_) for j in (k - 1, k + 1) if 0 <= j < len(rows)):
                    shifted += 1                 # (the driver's 240 Hz updates against the 50 Hz ticks)
                else:
                    per_ch[c] += 1
        # the phrases the driver started on the reference
        t0 = r["t0"]
        for tw, kind, reg, v in r["log"]:
            if kind == "T" and tw >= t0:
                sp_ref.append(int((tw - t0) * S.TICK_HZ // S.AS))
        diff = sum(per_ch)
        print("driver %-10s %5d ticks: %d channel ticks with sound, %d equal, %d alike, %d alike a tick off, %d differ "
              "(%.1f %%) [per channel %s]; phrases: reference %d, model %d, %d at the same tick (+-1)" % (
                  name, len(sc), n, exact, near, shifted, diff, 100.0 * diff / max(1, n), per_ch, len(sp_ref), len(sp_model),
                  sum(1 for k in sp_model if any(abs(k - j) <= 1 for j in sp_ref))))
    return ok


# ================================================================================================= MAME's audio

MAME_LUA = """
local m = manager.machine
local sp = m.devices[":maincpu"].spaces["program"]
local ev = {%(events)s}
local f = 0
emu.wait(%(start)f)
print("CAPTURE_START", emu.time())
for _, e in ipairs(ev) do
  while f < e[1] do emu.wait(1 / %(fps)f) f = f + 1 end
  sp:write_u8(0x803171, e[2])
end
emu.wait(%(tail)f)
m:exit()
"""
MAME_START = 3200                        # arcade frames: a quiet stretch of the attract mode (no game commands; the attract
                                         # mode's floor ($01: only priorities from 60 on) lifted by $02 first)
PIECES = [("floor 0", 0, [0x02], 0.1), ("tune $44", 2, [0x44], 26.0), ("effect $1A", 1700, [0x1A], 2.0), ("effect $22", 1830, [0x22], 3.0),
          ("effect $09", 2030, [0x09], 1.2), ("pokey $4A", 2130, [0x4A], 0.7), ("tune $49", 2230, [0x49], 4.4),
          ("music $42", 2530, [0x42], 18.0), ("stop", 3650, [0x00], 0.1), ("all $0B", 3700, [0x0B], 0.8),
          ("effect $26", 3800, [0x26], 2.0), ("speech $5A", 3950, [0x02, 0x5A], 1.0)]


def mame_capture(rate=48000):
    cache = BUILD / "sound_mame.npy"
    if cache.exists():
        return np.load(cache), rate
    from mame_roms import rompath
    ev = []
    for name, f, cmds, secs in PIECES:
        for i, c in enumerate(cmds):
            ev.append((f + i, c))
    start = (MAME_START + 0.5) / MAME_HZ             # (mid-frame: the game's own $03 at each vertical blank would
    #  replace a command written just before it)
    tail = max(f + secs * MAME_HZ for name, f, cmds, secs in PIECES) / MAME_HZ - ev[-1][0] / MAME_HZ + 1
    tmp = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    (tmp / "cap.lua").write_text(MAME_LUA % dict(events=", ".join("{%d, %d}" % e for e in ev), start=start,
                                                  fps=MAME_HZ, tail=tail))
    r = mamewin.run(["mame", "gauntlet", "-rompath", str(rompath()), "-window", "-nothrottle", "-skip_gameinfo",
                        "-seconds_to_run", "250", "-samplerate", str(rate), "-wavwrite", str(tmp / "out.wav"),
                        "-autoboot_script", str(tmp / "cap.lua")], capture_output=True, text=True, cwd=tmp)
    t0 = [l for l in r.stdout.splitlines() if l.startswith("CAPTURE_START")]
    if not t0:
        sys.exit("MAME failed:\n" + r.stdout + r.stderr)
    w = wave.open(str(tmp / "out.wav"))
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()).mean(1)
    x = x[int(round(float(t0[0].split()[1].replace(",", ".")) * rate)):]
    np.save(cache, x)
    return x, rate


YM_LEVEL = [0, 78, 178, 262, 369, 509, 701, 965, 1334, 1853, 2576, 3576, 5000, 7023, 9963, 14132]


def ym_render(regs_ticks, rate=48000, tick_hz=S.TICK_HZ):
    """the YM2149 (2 MHz) from its registers a tick: square waves, the 17-bit noise, the volume table"""
    n = int(len(regs_ticks) * rate / tick_hz)
    out = np.zeros(n)
    ph = [0.0, 0.0, 0.0]
    lfsr, nph, nout = 1, 0.0, 1
    per_s = int(rate / tick_hz)
    for k, r in enumerate(regs_ticks):
        a, b = int(k * rate / tick_hz), int((k + 1) * rate / tick_hz)
        m = b - a
        noise = np.zeros(m)
        if any(not (r[7] >> (3 + c)) & 1 and r[8 + c] for c in range(3)):
            step = 125000 / max(1, r[6] & 31) / rate
            for i in range(m):
                nph += step
                while nph >= 1:
                    nph -= 1
                    bit = (lfsr ^ (lfsr >> 3)) & 1
                    lfsr = (lfsr >> 1) | (bit << 16)
                    nout = lfsr & 1
                noise[i] = nout
        for c in range(3):
            v = YM_LEVEL[r[8 + c] & 15]
            if not v:
                continue
            p = (r[2 * c] | (r[2 * c + 1] & 15) << 8) or 1
            tone_on = not (r[7] >> c) & 1
            noise_on = not (r[7] >> (3 + c)) & 1
            f = 125000 / p
            t = ph[c] + np.arange(1, m + 1) * f / rate
            ph[c] = t[-1] % 1
            sq = (t % 1 < 0.5) if tone_on else np.ones(m, bool)
            nz = noise > 0.5 if noise_on else np.ones(m, bool)
            out[a:b] += v * (sq & nz)
    return out


def semitone_spectrum(x, rate, lo=40.0, hi=4000.0):
    """the power per semitone (MIDI notes) of a signal, summed over 8192-sample frames"""
    n = 8192
    w = np.hanning(n)
    acc = None
    for i in range(0, len(x) - n, n // 2):
        s = np.abs(np.fft.rfft(x[i:i + n] * w)) ** 2
        acc = s if acc is None else acc + s
    if acc is None:
        return None
    hz = np.fft.rfftfreq(n, 1 / rate)
    ok = (hz >= lo) & (hz < hi)
    notes = np.round(69 + 12 * np.log2(hz[ok] / 440)).astype(int)
    out = np.zeros(128)
    np.add.at(out, notes, acc[ok])
    return out


def corr(a, b, shift=0):
    a = np.log10(a + a.max() * 1e-4)
    b = np.log10(b + b.max() * 1e-4)
    b = np.roll(b, shift)
    sl = slice(30, 108)
    a, b = a[sl] - a[sl].mean(), b[sl] - b[sl].mean()
    return float((a * b).sum() / math.sqrt((a * a).sum() * (b * b).sum()))


def write_wavs(x, y, enc, starts, rate):
    """build/gauntlet/sound_mame.wav (MAME's audio of PIECES) and sound_ste.wav (the Player: the YM2149 rendered,
    the phrases' ADPCM decoded at 6258 Hz from their start ticks) for listening side by side"""
    z = y.copy()
    for k, ph in starts:
        pcm = np.array(S.adpcm_decode(enc["pcm"][ph]), float) * 256
        up = S.resample(pcm, S.STE_PCM_HZ, rate)
        a = int(k * rate / S.TICK_HZ)
        n = min(len(up), len(z) - a)
        z[a:a + n] += up[:n] * 0.5
    for name, w in (("sound_mame.wav", x), ("sound_ste.wav", z)):
        v = np.clip(w / (np.abs(w).max() or 1) * 30000, -32768, 32767).astype(np.int16)
        with wave.open(str(BUILD / name), "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(rate)
            o.writeframes(v.tobytes())


def test_mame(enc, rate=48000):
    x, rate = mame_capture(rate)
    # the Player on the same commands: tick = the command's time at 50 Hz
    end = max(f + secs * MAME_HZ for name, f, cmds, secs in PIECES)
    nt = int(end / MAME_HZ * S.TICK_HZ) + 2
    sc = [[] for _ in range(nt)]
    for name, f, cmds, secs in PIECES:
        for i, c in enumerate(cmds):
            sc[int(round((f + i) / MAME_HZ * S.TICK_HZ))].append(c)
    p = S.Player(enc)
    regs, starts = [], []
    for k, c in enumerate(sc):
        regs.append(p.tick(c))
        if p.speech is not None:
            starts.append((k, p.speech))
    y = ym_render(regs, rate)
    write_wavs(x, y, enc, starts, rate)
    good = True
    for name, f, cmds, secs in PIECES:
        if secs < 0.5 or name.startswith("speech"):
            continue
        a, b = int(f / MAME_HZ * rate), int((f / MAME_HZ + secs) * rate)
        sa, sb = semitone_spectrum(x[a:b], rate), semitone_spectrum(y[a:b], rate)
        if sa is None or sb is None:
            continue
        c0 = corr(sa, sb)
        others = {s: corr(sa, sb, s) for s in (-12, -1, 1, 12)}
        best = max(others, key=others.get)
        print("mame %-12s correlation %.2f (shifted: %s)%s" % (name, c0, " ".join(
            "%+d %.2f" % (s, v) for s, v in sorted(others.items())), "" if c0 >= others[best] else "  <- shift %+d" % best))
        good &= c0 >= others[best]
    # the speech: the TMS5220's samples (tools/sound.py SynthTMS, the reference board) and the STE's (6258 Hz, 8 bits;
    # what the ADPCM decodes to)
    # against MAME's waveform, aligned by cross-correlation
    name, f, cmds, secs = next(p_ for p_ in PIECES if p_[0].startswith("speech"))
    ph = S.phrase_of(cmds[-1])
    rec = S.record_all(BUILD)["p"][ph]
    pcm = np.array(rec["pcm"], float)
    pcm[pcm == -1] = 0
    a = int(f / MAME_HZ * rate)
    seg = x[a:a + int((secs + 0.5) * rate)]
    ste = np.array(S.adpcm_decode(S.adpcm_encode(np.frombuffer(S.phrase_pcm(rec), np.int8))), float)
    for what, y in (("TMS5220", S.resample(pcm, rec["rate"], rate)),
                    ("STE 8-bit", S.resample(np.frombuffer(S.phrase_pcm(rec), np.int8).astype(float), S.STE_PCM_HZ,
                                             rate)),
                    ("STE ADPCM", S.resample(ste, S.STE_PCM_HZ, rate))):
        cc = np.correlate(seg, y, "valid")
        lag = int(np.argmax(np.abs(cc)))
        r = float(np.corrcoef(seg[lag:lag + len(y)], y)[0, 1])
        print("mame speech phrase $%02X, %s samples: waveform correlation %.3f (%.0f ms after the command)" % (
            ph, what, r, lag * 1000 / rate))
        good &= r > 0.9
    return good


# ================================================================================================= the STE (Hatari)

HW_TEST = """; sound_test.py's STE program: src/sound_out.s from the VBL, a script of commands (one tick a VBL)
	section text,code
	clr.l	-(sp)
	move.w	#$20,-(sp)
	trap	#1
	addq.l	#6,sp
	move.w	#$2700,sr
	bsr	snd_out_init
	move.l	#vbl,$70.w
	move.w	#$2300,sr
.idle:	bra.s	.idle

vbl:	movem.l	d0-d1/a0-a1,-(sp)
	move.l	script_ptr,a0
.s:	move.w	(a0),d0
	cmp.w	tick,d0
	bne.s	.n
	move.w	2(a0),d0
	moveq	#0,d1
	move.b	snd_qhead,d1
	lea	snd_queue,a1
	move.b	d0,(a1,d1.w)
	addq.b	#1,d1
	and.b	#63,d1
	move.b	d1,snd_qhead
	addq.l	#4,a0
	bra.s	.s
.n:	move.l	a0,script_ptr
	addq.w	#1,tick
	bsr	snd_out_vbl
	movem.l	(sp)+,d0-d1/a0-a1
	rte

	include	"sound_out.s"

	section data,data
	even
script_ptr:	dc.l	script
script:		dc.w	%(script)s
		dc.w	-1,0

	section bss,bss
	even
tick:		ds.w	1
snd_queue:	ds.b	64
snd_qhead:	ds.b	1
	even
"""
HW_SCRIPT = [(0, 0x02), (5, 0x49), (260, 0x1A), (360, 0x5A), (420, 0x0B), (480, 0x4A), (520, 0x26), (600, 0x42),
             (1000, 0x43)]
HW_PIECES = [("tune $49", 5, 250), ("effect $1A", 260, 355), ("effect $0B", 420, 475), ("pokey $4A", 480, 515),
             ("effect $26", 520, 595), ("music $42", 600, 1000), ("its fade", 1000, 1240)]
HATARI = os.environ.get("HATARI", "/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari")
TOS = os.environ.get("TOS", "/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img")


def hatari_capture(rate=48000, seconds=32):
    """the STE program in its own Hatari (STE, --sound), its audio recorded (the recsound shortcut): hatari.wav"""
    d = BUILD / "sndhw"
    d.mkdir(exist_ok=True)
    (d / "hwtest.s").write_text(HW_TEST % dict(script=",".join("%d,$%02X" % e for e in HW_SCRIPT)))
    src = HERE.parents[1] / "src"
    for cmd in ([VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(src), "-I", str(BUILD), "-o", str(d / "hw.o"),
                 str(d / "hwtest.s")], [VLINK, "-b", "ataritos", "-o", str(d / "HWTEST.PRG"), str(d / "hw.o")]):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    for f in ("hatari.wav", "cmd.fifo"):
        if (d / f).exists():
            (d / f).unlink()
    p = subprocess.Popen([HATARI, "--machine", "ste", "--memsize", "4", "--tos", TOS, "--fast-boot", "true",
                          "--cpu-exact", "true", "--compatible", "true", "--sound", str(rate), "--confirm-quit", "off",
                          "--statusbar", "false", "--cmd-fifo", str(d / "cmd.fifo"), "--log-file", str(d / "hatari.log"),
                          "HWTEST.PRG"], cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if (d / "cmd.fifo").exists():
            break
        time.sleep(0.2)
    time.sleep(1)
    (d / "cmd.fifo").write_text("hatari-shortcut recsound\n")
    time.sleep(seconds)
    (d / "cmd.fifo").write_text("hatari-shortcut recsound\n")
    time.sleep(1)
    p.kill()
    p.wait()
    w = wave.open(str(d / "hatari.wav"))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()).mean(1).astype(float), \
        w.getframerate()


def test_hatari(enc):
    """the program's audio in Hatari against the Player: the semitone spectra of the pieces, the phrase's waveform"""
    x, rate = hatari_capture()
    sc = [[] for _ in range(1250)]
    for t, c in HW_SCRIPT:
        sc[t].append(c)
    p = S.Player(enc)
    regs, starts = [], []
    for k, c in enumerate(sc):
        regs.append(p.tick(c))
        if p.speech is not None:
            starts.append((k, p.speech))
    y = ym_render(regs, rate)
    n = rate // S.TICK_HZ

    def env(z):
        k = len(z) // n
        e = np.sqrt((z[:k * n].reshape(k, n) ** 2).mean(1))
        return e / (e.max() or 1)
    off = int(np.nonzero(env(x) > 0.02)[0][0]) - int(np.nonzero(env(y) > 0.02)[0][0])   # (the first sound)
    xa = x[off * n:]
    good = True
    for name, a, b in HW_PIECES:
        sa, sb = semitone_spectrum(xa[a * n:b * n], rate), semitone_spectrum(y[a * n:b * n], rate)
        c0 = corr(sa, sb)
        others = {s: corr(sa, sb, s) for s in (-12, -1, 1, 12)}
        print("hatari %-12s correlation %.2f (shifted: %s)" % (name, c0, " ".join(
            "%+d %.2f" % (s, v) for s, v in sorted(others.items()))))
        good &= c0 >= max(others.values())
    k, ph = starts[0]
    up = S.resample(np.array(S.adpcm_decode(enc["pcm"][ph]), float), S.STE_PCM_HZ, rate)
    seg = xa[(k - 15) * n:(k + 45) * n]
    cc = np.correlate(seg, up, "valid")
    lag = int(np.argmax(np.abs(cc)))
    r = abs(float(np.corrcoef(seg[lag:lag + len(up)], up)[0, 1]))
    print("hatari speech phrase $%02X (the DMA sound): waveform correlation %.3f" % (ph, r))
    return good and r > 0.8


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ticks = None
    if "--ticks" in sys.argv:
        ticks = int(sys.argv[sys.argv.index("--ticks") + 1])
        args = [a for a in args if a != str(ticks)]
    which = args or ["player", "driver", "mame", "hatari"]
    enc = S.encode_all(S.record_all(BUILD))
    ok = True
    if "player" in which:
        ok &= test_player(enc, ticks)
    if "driver" in which:
        ok &= test_driver(enc, ticks or 3000)
    if "mame" in which:
        ok &= test_mame(enc)
    if "hatari" in which:
        ok &= test_hatari(enc)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
