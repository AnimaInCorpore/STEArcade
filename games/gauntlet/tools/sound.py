"""Gauntlet's sound for the STE: what each command plays on the reference sound board (tools/machine.py's 6502, its
YM2151 / POKEY / TMS5220C, the main CPU held), turned into STE data (YM2149 streams, ADPCM speech for the DMA sound)
and the model of src/sound_out.s.

    venv/bin/python games/gauntlet/tools/sound.py [--again]    # record (cached: sound_rec.pkl), emit build/gauntlet/

THE DRIVER (the 6502 program 136037-120.16r / -119.16s; see tools/sound_hle.py for the protocol).  Commands are
queued by the NMI and run by the main loop: type $5D6A[cmd], argument $5E4C[cmd], handler $4630[type].
  * 12 logical channels: 0-3 the POKEY's, 4-11 the YM2151's channels 0-7.  30 voices.  A sound (type 6, argument =
    the sound 0-$43) is a chain of entries ($5F36[sound], next $63E2[x]): channel $6166[x], priority $5FBE[x], data
    $623A/$633A.  Each entry starts a voice ($44CD): a free voice (none free: the channel's lowest voice is taken if
    the new priority is at least its own, else the command's remaining entries are dropped), inserted into its
    channel's list ($07E6, ascending priority); a voice of the same priority on that channel is killed (the new one
    replaces it).  Every voice runs every tick; only the channel's last (highest priority) one reaches the chip, so
    a lower voice is heard again when the higher one ends.  ($5F7A[sound] = $FF for every sound: no "already
    playing" check.)
  * $00 stop all ($8186), $30/$32/$34/$36 kill the voices of a sound ($437C), $43 fades the attract music ($42,
    $43C3), $48 fades the voices of priority 2 ($43FA).  A fade sets the voice's volume envelope ($078C = $D0 ...):
    measured below (FADE_*).
  * Speech ($4428 / $58AB): a phrase (0-$8C) with priority $65D0[p] >= the floor $1B ($01 -> $F0, $02 -> 0)
    starts at once when the chip is idle; while one speaks, an 8-deep queue: a higher priority empties the queue and
    becomes the current priority, the same priority is appended, a lower one is dropped.  A phrase sets the squeak
    bit (the TMS5220's clock: $6543[p] bit 7) and lowers the YM / POKEY gains ($1020) by $6543[p] & 15 until 25 IRQs
    after its data are written; the next queued phrase starts after its 17 trailing zero bytes.
  * The floor $1B also mutes a channel whose top voice's priority * 4 + 1 is below it (the attract mode sends $01:
    only the title music $42 and the priority 63 sounds are heard; $02 after a coin); the voices run on.
  * $DD-$E0 the mixer ($1020: YM gain bits 0-2, POKEY bits 3-4, speech bits 5-7), written while no phrase speaks.

THE RECORDINGS: each sound alone after a stop-all (record_sound): per voice (= channel) and STE tick (TICK_HZ, the
STE's VBL: 50 Hz on a PAL STE, so the music keeps its tempo while the game itself runs at the STE's speed) the YM2149
form of what reaches the chip: the POKEY channel's tone or noise; the YM2151 channel's loudness from its carriers
(engine/opm.py's envelopes, averaged over 4 points a tick) and its timbre (fm_timbre: the four operators rendered with
their envelopes held, the third-octave spectrum matched against square waves, the YM's noises and both: many of
Gauntlet's effects are feedback-7 FM noise, which a square at the carrier's pitch misses); the voice's lifetime from
the driver's lists ($07E6) so that a silent voice still masks the lower ones, and its tail (the chip's release, up to
TAIL_MAX ticks).  Looping voices (the attract music $42: one channel loops for ever) by the driver's voice tables
repeating (find_loop).  Each phrase alone (record_phrase): the TMS5220C's output (MAME's process(): lattice filter,
interpolation, chirp, LFSR; SynthTMS below, equal to MAME's audio: waveform correlation 0.998) at its stream rate
(8135 Hz, 9943 Hz with the squeak bit), resampled to 6258 Hz, 4-bit ADPCM.

THE STE (Player below = src/sound_out.s): the commands each tick; the voices as the driver keeps them; each channel's
top voice (live by priority, else a tail); the floor and the mixer's gains as volume offsets; the 12 channels on the
YM2149's 3 (the loudest, a channel keeps its YM channel on a tie); a phrase's ADPCM decoded into a buffer the DMA
sound plays.
"""
from pathlib import Path
import math
import pickle
import sys

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parent), str(HERE.parents[3] / "engine")]
import machine as MC
import gauntlet_sound as GS
from tms5220 import TMS5220C, RELOAD_TABLE, NUM_K
from opm import OPM

AS = MC.AS
TICK_HZ = 50                                     # the STE's VBL (PAL; 49.97 Hz)
STE_PCM_HZ = 6258                                # the DMA sound's rate (mode 0)
CHANNELS = 12                                    # 0-3 POKEY, 4-11 YM2151 0-7
NVOICES = 30
SOUNDS = 0x44                                    # sound numbers (type 6 arguments) 0-$43
PHRASES = 0x8D                                   # speech phrases 0-$8C


def srom():
    return MC.sound_rom()


R = None


def rom():
    global R
    if R is None:
        R = srom()
    return R


def cmd_type(c):
    return rom()[0x5D6A + c]


def cmd_arg(c):
    return rom()[0x5E4C + c]


def chain(sound):
    """[(channel, priority)] the sound's voices in the order the driver starts them"""
    r = rom()
    x = r[0x5F36 + sound]
    out = []
    while True:
        out.append((r[0x6166 + x], r[0x5FBE + x]))
        x = r[0x63E2 + x]
        if not x:
            return out


def phrase_info(p):
    """(priority, squeak, gain drop) of a phrase"""
    r = rom()
    return r[0x65D0 + p], r[0x6543 + p] >> 7, r[0x6543 + p] & 15


def sound_of(c):
    """the sound a type 6 command starts, else None"""
    return cmd_arg(c) if cmd_type(c) == 6 else None


def phrase_of(c):
    return cmd_arg(c) if cmd_type(c) == 0x0A else None


# ================================================================================================= the TMS5220C's audio

ENERGY = (0, 1, 2, 3, 4, 6, 8, 11, 16, 23, 33, 47, 63, 85, 114, 0)
PITCH = (0, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
         41, 42, 44, 46, 48, 50, 52, 53, 56, 58, 60, 62, 65, 68, 70, 72, 76, 78, 80, 84, 86, 91, 94, 98, 101, 105,
         109, 114, 118, 122, 127, 132, 137, 142, 148, 153, 159)
KTABLE = (
    (-501, -498, -497, -495, -493, -491, -488, -482, -478, -474, -469, -464, -459, -452, -445, -437,
     -412, -380, -339, -288, -227, -158, -81, -1, 80, 157, 226, 287, 337, 379, 411, 436),
    (-328, -303, -274, -244, -211, -175, -138, -99, -59, -18, 24, 64, 105, 143, 180, 215,
     248, 278, 306, 331, 354, 374, 392, 408, 422, 435, 445, 455, 463, 470, 476, 506),
    (-441, -387, -333, -279, -225, -171, -117, -63, -9, 45, 98, 152, 206, 260, 314, 368),
    (-328, -273, -217, -161, -106, -50, 5, 61, 116, 172, 228, 283, 339, 394, 450, 506),
    (-328, -282, -235, -189, -142, -96, -50, -3, 43, 90, 136, 182, 229, 275, 322, 368),
    (-256, -212, -168, -123, -79, -35, 10, 54, 98, 143, 187, 232, 276, 320, 365, 409),
    (-308, -260, -212, -164, -117, -69, -21, 27, 75, 122, 170, 218, 266, 314, 361, 409),
    (-256, -161, -66, 29, 124, 219, 314, 409),
    (-256, -176, -96, -15, 65, 146, 226, 307),
    (-205, -132, -59, 14, 87, 160, 234, 307))
CHIRP = (0x00, 0x03, 0x0f, 0x28, 0x4c, 0x6c, 0x71, 0x50, 0x25, 0x26, 0x4c, 0x44, 0x1a, 0x32, 0x3b, 0x13,
         0x37, 0x1a, 0x25, 0x1f, 0x1d) + (0,) * 31
INTERP = (0, 3, 3, 3, 2, 2, 1, 1)


def _s8(v):
    return v - 256 if v & 0x80 else v


def _mm(a, b):
    """matrix_multiply"""
    while a > 511:
        a -= 1024
    while a < -512:
        a += 1024
    while b > 16383:
        b -= 32768
    while b < -16384:
        b += 32768
    return (a * b) >> 9


def _clip_analog(c):
    c = max(-2048, min(2047, c))
    c &= ~0xF
    return (c << 4) | ((c & 0x7F0) >> 3) | ((c & 0x400) >> 10)


class SynthTMS(TMS5220C):
    """engine/tms5220.py's chip with MAME's sample generator (tms5220.cpp process(), lattice_filter(), clip_analog();
    tms5110r.hxx's tms5220_coeff; no TMS5220_PERFECT_INTERPOLATION_HACK, analog output): the samples go to `out`
    (16-bit values; -1 while idle), `out_start` = the stream index of out[0]"""

    def __init__(self, board, clock=None):
        self.out = []
        self.out_start = 0
        super().__init__(board) if clock is None else super().__init__(board, clock)

    def device_reset(self):
        super().device_reset()
        self.current_energy = self.previous_energy = self.current_pitch = 0
        self.current_k = [0] * NUM_K
        self.inhibit = True
        self.pitch_count = 0
        self.pitch_zero = False
        self.RNG = 0x1FFF
        self.u = [0] * 11
        self.x = [0] * 10
        self.excitation = 0

    reset = device_reset

    def process(self, size):
        out = self.out
        while size > 0:
            if self.TALKD:
                if self.IP == 0 and self.PC == 12 and self.subcycle == 1:
                    self.IP = RELOAD_TABLE[self.c_variant_rate & 3]
                    self.parse_frame()
                    if self.new_energy == 0x0F:
                        self.TALK = self.SPEN = False
                        self.update_fifo_status_and_ints()
                    ou, nu = self.OLDP, self.new_pitch == 0
                    if (not ou and nu) or (ou and not nu) or (self.OLDE and self.new_energy != 0) or (ou and self.new_energy == 0):
                        self.inhibit = True
                    else:
                        self.inhibit = False
                else:
                    inh = 0 if (self.inhibit and self.IP != 0) else 1
                    if self.subcycle == 2:
                        pc = self.PC
                        sh = INTERP[self.IP]
                        if pc == 0:
                            if self.IP == 0:
                                self.pitch_zero = False
                            e = self.current_energy
                            self.current_energy = (e + (((ENERGY[self.new_energy] - e) * inh) >> sh)) * (1 - self.zpar)
                        elif pc == 1:
                            p = self.current_pitch
                            self.current_pitch = (p + (((PITCH[self.new_pitch] - p) * inh) >> sh)) * (1 - self.zpar)
                        elif 2 <= pc <= 11:
                            i = pc - 2
                            k = self.current_k[i]
                            z = self.zpar if i < 4 else self.uv_zpar
                            self.current_k[i] = (k + (((KTABLE[i][self.new_k[i]] - k) * inh) >> sh)) * (1 - z)
                if self.OLDP:
                    self.excitation = ~0x3F if self.RNG & 1 else 0x40
                else:
                    self.excitation = _s8(CHIRP[min(self.pitch_count, 51)])
                r = self.RNG
                for _ in range(20):
                    bit = ((r >> 12) ^ (r >> 3) ^ (r >> 2) ^ r) & 1
                    r = ((r << 1) | bit) & 0xFFFF
                self.RNG = r
                s = self.lattice()
                while s > 16383:
                    s -= 32768
                while s < -16384:
                    s += 32768
                out.append(_clip_analog(s))
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7 and self.inhibit:
                        self.pitch_zero = True
                    if self.IP == 7:
                        self.OLDE = self.new_energy == 0
                        self.OLDP = self.new_pitch == 0
                        self.TALKD = self.TALK
                        self.update_fifo_status_and_ints()
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1
                self.pitch_count += 1
                if self.pitch_count >= self.current_pitch or self.pitch_zero:
                    self.pitch_count = 0
                self.pitch_count &= 0x1FF
            else:
                self.subcycle += 1
                if self.subcycle == 2 and self.PC == 12:
                    if self.IP == 7:
                        self.TALKD = self.TALK
                        self.update_fifo_status_and_ints()
                        if not self.TALK and self.SPEN:
                            self.TALK = True
                    self.subcycle = self.subc_reload
                    self.PC = 0
                    self.IP = (self.IP + 1) & 7
                elif self.subcycle == 3:
                    self.subcycle = self.subc_reload
                    self.PC += 1
                out.append(-1)
            size -= 1

    def lattice(self):
        u, x, k = self.u, self.x, self.current_k
        u[10] = _mm(self.previous_energy, self.excitation << 6)
        for i in range(9, -1, -1):
            u[i] = u[i + 1] - _mm(k[i], x[i])
        for i in range(9, 0, -1):
            x[i] = x[i - 1] + _mm(k[i - 1], u[i - 1])
        x[0] = u[0]
        self.previous_energy = self.current_energy
        return u[0]

    def set_clock(self, clock):
        """the squeak bit: the stream's rate changes; the samples so far are kept with their rate"""
        if clock != self.clock:
            self.stream_update()
            self.rate_marks.append((len(self.out), clock // 80))
        super().set_clock(clock)


# ================================================================================================= the recorder

class RecSound(GS.SoundBoard):
    """the 6502's bus with every chip write logged: (time, kind, register, value); kind Y (YM2151 register write),
    P (POKEY), S (speech data), M (mixer $1020), C (soundctl bit, value), T (the driver starts a phrase)"""

    def __init__(self, board):
        super().__init__(board)
        self.tms = SynthTMS(board)
        self.tms.rate_marks = []
        self.log = []
        self.ym_addr = 0

    def wr(self, a, v):
        if a == 0x2B and v == 0x80:                     # the driver starts a phrase ($58AB: $2B = $80)
            self.log.append((self.b.now(), "T", 0, self.ram[0x31]))
        if a < 0x4000 and a & 0x1000:
            k = a & 0x30
            t = self.b.now()
            if a & 0x800:
                if k == 0x00:
                    self.log.append((t, "P", a & 0xF, v))
                elif k == 0x10:
                    if a & 1:
                        self.log.append((t, "Y", self.ym_addr, v))
                    else:
                        self.ym_addr = v
                elif k == 0x20:
                    self.log.append((t, "S", 0, v))
            elif k == 0x20:
                self.log.append((t, "M", 0, v))
            elif k == 0x30:
                self.log.append((t, "C", a & 7, v >> 7 & 1))
        return super().wr(a, v)


class RecBoard(MC.Gauntlet):
    """the reference board's sound part alone: the main CPU held (suspended), the 6502 booted by a command 0, its
    replies dropped (the latch never pending), the watchdog quiet"""

    def __init__(self):
        super().__init__()
        self.main.suspended = True
        self.rebuild()
        self.sound_reset_w(1)
        self.soundlatch.write(0)
        self.halted = False
        self.run_until(AS // 2)

    def make_sound(self):
        self.snd_devices = RecSound(self)
        self.sound = MC.Exec("audiocpu", self.snd_devices.exec_core(), MC.SOUND_HZ)
        self.sound.suspended = False
        from pokey import CLOCK
        self.pokey = MC.Exec("pokey", self.snd_devices.pokey, CLOCK)
        self.execs += [self.sound, self.pokey]

    def vblank_begin(self):
        self.watchdog = 0
        super().vblank_begin()

    def reply_written(self, v):
        pass

    def _halt(self):
        self.halted = True
        self.stop = True

    def run_until(self, t):
        self.timer_at(t, self._halt)
        self.halted = False
        while not self.halted:
            self.stop = False
            self.timeslice()

    def command(self, v):
        self.soundlatch.write(v)

    @property
    def sram(self):
        return self.snd_devices.ram

    def voices(self):
        """{voice: (channel, priority, sound)} the driver's live voices"""
        ram = self.sram
        out = {}
        for ch in range(CHANNELS):
            y = ram[0x7E6 + 0x1E + ch]
            while y:
                v = y - 1
                out[v] = (ch, ram[0x3AE + v] >> 2, ram[0x228 + v])
                y = ram[0x7E6 + v]
        return out

    def speaking(self):
        return self.sram[0x2B] != 0


def tick_as(k, hz=TICK_HZ):
    return k * AS // hz


def record_raw(cmds, ticks, quiet=20, board=None, stop_first=True, hz=TICK_HZ, snap=False):
    """runs the commands [(tick, command)] from a stop-all; per tick the live voices and whether speech is busy; the
    chip write log (snap: and the voice tables $228-$803 at each tick's end).  Ends after `ticks` ticks, or `quiet`
    ticks without voices or speech after the last command."""
    b = board or RecBoard()
    if stop_first:
        b.command(0)
        b.run_until(b.base + AS // 5)
    log0 = len(b.snd_devices.log)
    out0 = len(b.snd_devices.tms.out)
    t0 = b.base
    states = []
    pend = sorted(cmds)
    q = 0
    last = max(t for t, c in pend) if pend else 0
    for k in range(ticks):
        while pend and pend[0][0] == k:
            b.command(pend.pop(0)[1])
            # (two commands in one tick: 0.5 ms apart; the 6502 takes one in 40 us)
            b.run_until(b.now() + AS // 2000) if pend and pend[0][0] == k else None
        b.run_until(t0 + tick_as(k + 1, hz))
        v = b.voices()
        sp = b.speaking()
        states.append((v, sp, bytes(b.sram[0x228:0x804]) if snap else None))
        if k > last:
            q = 0 if (v or sp) else q + 1
            if quiet and q >= quiet:
                break
    tms = b.snd_devices.tms
    return dict(t0=t0, hz=hz, states=states, log=b.snd_devices.log[log0:], pcm=tms.out[out0:],
                pcm_start=out0, rate_marks=list(tms.rate_marks), board=b)


# ================================================================================================= the chips -> YM2149

import capsnd
from capsnd import ym_period, ym_volume

POKEY_HZ = MC.SOUND_HZ
POKEY_GAIN = 1.0                                 # a POKEY channel at volume 15 against one YM2151 carrier at full level
SUB = 4                                          # points a tick the loudness is averaged over


def pokey_channel(regs, ch):
    """(hz, amplitude, noise) of a POKEY channel from its registers: tone hz (pure tones), else the noise's rate"""
    audctl = regs[8]
    audc = regs[2 * ch + 1]
    vol = audc & 15
    if not vol or audc & 0x10:
        return 0.0, 0.0, False
    base = POKEY_HZ / (114 if audctl & 0x01 else 28)
    f = regs[2 * ch]
    if ch == 1 and audctl & 0x10 or ch == 3 and audctl & 0x08:      # the high half of a 16-bit pair
        f16 = f << 8 | regs[2 * ch - 2]
        hi = audctl & (0x40 if ch == 1 else 0x20)
        rate = POKEY_HZ / (f16 + 7) if hi else base / (f16 + 1)
    elif ch == 0 and audctl & 0x10 or ch == 2 and audctl & 0x08:    # the low half: not heard
        return 0.0, 0.0, False
    elif ch == 0 and audctl & 0x40 or ch == 2 and audctl & 0x20:
        rate = POKEY_HZ / (f + 4)
    else:
        rate = base / (f + 1)
    amp = vol / 15 * POKEY_GAIN
    if audc & 0x20:
        return rate / 2, amp, False
    return rate, amp, True


def noise_period(rate):
    return max(1, min(31, round(125000 / rate))) if rate > 0 else 31


def ym_form(f, amp, noise):
    """a POKEY channel's (hz, amplitude, noise) -> (period, noise period, mode, volume)"""
    v = ym_volume(amp)
    if not v or f <= 0:
        return (0, 0, 0, 0)
    if noise:
        return (0, noise_period(f), 2, v)
    return (ym_period(f), 0, 1, v)


def chip_ticks(log, t0, ticks, hz=TICK_HZ):
    """per tick: the 12 logical channels' YM2149 values (period, noise period, mode, volume; mode 1 tone, 2 noise,
    3 both), from every chip write of the board's life (log from time 0).  The FM channels' loudness from their
    carriers averaged over SUB points, their timbre (fm_timbre) at the tick's end"""
    chip = OPMFull(MC.YM_HZ)
    pk = [0] * 16
    out = []
    k = 0
    n = len(log)
    egr = chip.eg_rate

    def adv(t):
        c = t * int(egr * 10 ** 6) // (AS * 10 ** 6)
        if c > chip.counter:
            chip.advance(c - chip.counter)

    for tk in range(ticks):
        amps = [0.0] * CHANNELS
        for j in range(SUB):
            t = t0 + tick_as(tk, hz) + (j + 1) * (tick_as(tk + 1, hz) - tick_as(tk, hz)) // SUB
            while k < n and log[k][0] <= t:
                tw, kind, r, v = log[k]
                if kind == "Y":
                    adv(tw)
                    chip.write(r, v)
                elif kind == "P":
                    pk[r] = v
                k += 1
            adv(t)
            for c in range(4):
                amps[c] += pokey_channel(pk, c)[1] / SUB
            for c in range(8):
                amps[4 + c] += chip.channel(c)[1] / SUB
        row = []
        for c in range(4):
            f, a, noise = pokey_channel(pk, c)
            row.append(ym_form(f, amps[c], noise))
        for c in range(8):
            v = ym_volume(amps[4 + c])
            if not v:
                row.append((0, 0, 0, 0))
            else:
                per, np_, mode = fm_timbre(chip.timbre_key(c))
                row.append((per, np_, mode, v))
        out.append(row)
    return out


# ================================================================================================= FM timbres

import numpy as np
from opm import SLOT_OFFSET, NOTE
from opn import CARRIERS

FM_FS = MC.YM_HZ / 64                            # the YM2151's sample rate
FM_N = 8192                                      # samples rendered to classify a timbre (146 ms)
DT2 = (1.0, 2 ** (600 / 1200), 2 ** (781 / 1200), 2 ** (950 / 1200))
ALG_OPS = [(1, 2, 3, 0, 0, 0), (0, 5, 3, 0, 0, 0), (0, 2, 6, 0, 0, 0), (1, 0, 7, 0, 0, 0),
           (1, 0, 3, 0, 1, 0), (1, 1, 1, 0, 1, 1), (1, 0, 0, 0, 1, 1), (0, 0, 0, 1, 1, 1)]   # ymfm s_algorithm_ops
NOISE_FLAT = 0.35                                # the spectrum's share in its 8 strongest peaks below which it is noise
TONE_CARRIER = 0.3                               # the carrier's own pitch is kept while its peak is this strong


class OPMFull(OPM):
    """engine/opm.py with every operator's envelope (the modulators decide the timbre)"""

    def advance(self, clocks):
        end = self.counter + clocks
        for ch in range(8):
            for op in range(4):
                self.run_op(ch, op, self.counter, end)
        self.counter = end

    def base_hz(self, ch):
        kc = self.regs[0x28 + ch]
        octave, note = (kc >> 4) & 7, NOTE.get(kc & 15, 11)
        semis = (octave - 4) * 12 + note - 8 + (self.regs[0x30 + ch] >> 2) / 64
        return 440.0 * 2 ** (semis / 12) * self.clock / 3579545

    def timbre_key(self, ch):
        """(algorithm, feedback, per operator (pitch in 1/32 semitones, attenuation / 16)): what the rendering of a
        channel depends on"""
        r = self.regs
        base = self.base_hz(ch)
        ops = []
        for op in range(4):
            o = SLOT_OFFSET[op]
            m = r[0x40 + ch + o] & 15
            f = base * (m if m else 0.5) * DT2[r[0xC0 + ch + o] >> 6]
            att = min(self.ops[ch][op].att + ((r[0x60 + ch + o] & 127) << 3), 0x3FF)
            ops.append((round(math.log2(max(f, 1.0)) * 12 * 32), att >> 4))
        return (r[0x20 + ch] & 7, (r[0x20 + ch] >> 3) & 7, tuple(ops))


def fm_render(key, n=FM_N):
    """the channel's output (ymfm's output_4op with sines; envelopes held) for a timbre key"""
    alg, fb, ops = key
    t = np.arange(n)
    freq = [2 ** (p / (12 * 32)) for p, a in ops]
    amp = [0.0 if a >= 63 else 2 ** (-(a * 16 + 8) / 64) for p, a in ops]
    ph = [t * (f / FM_FS) for f in freq]
    if fb and amp[0] > 0:
        o1 = np.empty(n)
        f0, f1 = 0.0, 0.0
        sh = 8191 / (1 << (10 - fb)) / 1024
        inc = freq[0] / FM_FS
        a0 = amp[0]
        tau = 2 * math.pi
        sin = math.sin
        for i in range(n):
            v = a0 * sin(tau * (i * inc + (f0 + f1) * sh))
            o1[i] = v
            f0, f1 = f1, v
    else:
        o1 = amp[0] * np.sin(2 * np.pi * ph[0])
    out = {0: 0.0, 1: o1}
    a = ALG_OPS[alg]
    k = 4.0                                      # (opout >> 1) in 10-bit phase units: x * 8191 / 2 / 1024 cycles
    out[2] = amp[1] * np.sin(2 * np.pi * (ph[1] + k * out[a[0]]))
    out[5] = out[1] + out[2]
    out[3] = amp[2] * np.sin(2 * np.pi * (ph[2] + k * out[a[1]]))
    out[6] = out[1] + out[3]
    out[7] = out[2] + out[3]
    o4 = amp[3] * np.sin(2 * np.pi * (ph[3] + k * out[a[2]]))
    y = o4 + (out[1] if a[3] else 0) + (out[2] if a[4] else 0) + (out[3] if a[5] else 0)
    return y


_timbres = {}
BANDS = np.array([20 * 2 ** (i / 3) for i in range(31)])     # third-octave band edges, 20 Hz - 20 kHz
TOP_HZ = 12000


def _band_index(hz):
    return np.searchsorted(BANDS, hz) - 1


def _norm(e):
    t = e.sum()
    return e / t if t > 0 else e


def square_bands(f):
    """a square wave's power (odd harmonics, 1 / k^2) in the bands"""
    e = np.zeros(len(BANDS) - 1)
    k = 1
    while k * f < TOP_HZ:
        b = _band_index(k * f)
        if 0 <= b < len(e):
            e[b] += 1.0 / (k * k)
        k += 2
    return _norm(e)


_noise_cache = {}


def noise_bands(np_):
    """the YM2149's noise (an LFSR shifted at 125 kHz / period): power density sinc^2(f / rate), in the bands"""
    r = _noise_cache.get(np_)
    if r is None:
        rate = 125000 / np_
        f = np.linspace(1, TOP_HZ, 6000)
        d = np.sinc(f / rate) ** 2
        b = _band_index(f)
        e = np.zeros(len(BANDS) - 1)
        ok = (b >= 0) & (b < len(e))
        np.add.at(e, b[ok], d[ok])
        r = _noise_cache[np_] = _norm(e)
    return r


def fm_bands(key, n=FM_N):
    y = fm_render(key, n)
    s = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    hz = np.fft.rfftfreq(len(y), 1 / FM_FS)
    b = _band_index(hz)
    e = np.zeros(len(BANDS) - 1)
    ok = (b >= 0) & (b < len(e)) & (hz < TOP_HZ)
    np.add.at(e, b[ok], s[ok])
    return _norm(e), s, hz


def hellinger(p, q):
    return float(((np.sqrt(p) - np.sqrt(q)) ** 2).sum())


def fm_timbre(key):
    """(period, noise period, mode) of the YM2149 sound closest to the channel's: mode 1 tone, 2 noise, 3 both.  The
    rendering's third-octave spectrum (fm_render: the operators with sines, envelopes held) against those of square
    waves at the carrier's pitch and at the rendering's strongest peaks (and half and a third of the first), of the
    YM's 31 noises and of the best tone with the best noise (the Hellinger distance of the band distributions)"""
    r = _timbres.get(key)
    if r is not None:
        return r
    alg, fb, ops = key
    p, s, hz = fm_bands(key)
    fc = 2 ** (ops[CARRIERS[alg][-1]][0] / 384)
    cands = [fc]
    pk = np.nonzero((s[1:-1] > s[:-2]) & (s[1:-1] >= s[2:]))[0] + 1
    pk = pk[(hz[pk] >= 25) & (hz[pk] < TOP_HZ)]
    pk = pk[np.argsort(s[pk])[::-1]][:8]
    for i, b in enumerate(pk):
        a_, b_, c_ = (math.log(s[b + d] + 1e-30) for d in (-1, 0, 1))
        den = a_ - 2 * b_ + c_
        f = float((b + (0.5 * (a_ - c_) / den if den else 0.0)) * FM_FS / FM_N)
        cands.append(f)
        if i == 0:
            cands += [f / 2, f / 3]
    best_t = None
    for f in cands:
        per = ym_period(f)
        if per <= 0:
            continue
        d = hellinger(p, square_bands(125000 / per))
        if best_t is None or d < best_t[0]:
            best_t = (d, per)
    best_n = min((hellinger(p, noise_bands(n)), n) for n in range(1, 32))
    both = hellinger(p, (square_bands(125000 / best_t[1]) + noise_bands(best_n[1])) / 2)
    if both < best_t[0] and both < best_n[0]:
        r = (best_t[1], best_n[1], 3)
    elif best_n[0] < best_t[0]:
        r = (0, best_n[1], 2)
    else:
        r = (best_t[1], 0, 1)
    _timbres[key] = r
    return r


# ================================================================================================= recordings

VOICE_ARRAYS = range(0x228, 0x804, 0x1E)         # the driver's per-voice tables (30 bytes each)
LOOP_VERIFY = 300                                # ticks a loop must repeat for after its first repeat
LOOP_MATCH = 0.9                                 # ... in this share of them (the chip model's envelopes carry over)
SOUND_CAP = 7000                                 # ticks a sound is recorded for at most (140 s)
FADE_STEP = 11                                   # a fade ($43 / $48): the volume one lower every this many ticks
FADE_END = 15                                    # ... and the voice gone when it is this much lower


def sound_command(s):
    return next(c for c in range(0xE2) if sound_of(c) == s)


def phrase_command(p):
    return next(c for c in range(0xE2) if phrase_of(c) == p)


def find_loop(snaps, y, rows, ch):
    """(start, end) for voice y on channel ch: its tables at the end of tick `end` equal those at the end of an earlier
    tick start - 1 (the first or the latest such tick), so rows from `start` on repeat with period end + 1 - start;
    checked over LOOP_VERIFY ticks of its rows (LOOP_MATCH of them equal).  None if none"""
    first, last = {}, {}
    for k, sn in enumerate(snaps):
        if k + LOOP_VERIFY >= len(rows):
            return None
        key = bytes(sn[a - 0x228 + y] for a in VOICE_ARRAYS)
        for j in {first.get(key), last.get(key)} - {None}:
            per = k - j
            same = sum(1 for i in range(k + 1, k + 1 + LOOP_VERIFY)
                       if rows[i][ch] == rows[i - per][ch] or (rows[i][ch][3] == 0 and rows[i - per][ch][3] == 0))
            if same >= LOOP_MATCH * LOOP_VERIFY:
                return j + 1, k
        first.setdefault(key, k)
        last[key] = k
    return None


TAIL_MAX = 300                                   # ticks recorded after the last voice ended (the chip's release)
TEST_SOUNDS = {0, 1}                             # the service mode's sound tests ($04 YM2151, $05 POKEY): cut
TEST_CAP = 1500


def record_sound(s, cap=None):
    """a sound alone: {voices: [(channel, priority, life, rows, loop)], ticks}; rows [(period, noise period, mode,
    volume)] a tick from the start up to the voice's audible end (or its life), life the ticks it is in the driver's
    lists (-1: for ever, the sound loops from rows[loop] after its last row)"""
    cap = cap or (TEST_CAP if s in TEST_SOUNDS else SOUND_CAP)
    b = RecBoard()
    r = record_raw([(0, sound_command(s))], cap, quiet=TAIL_MAX, board=b, snap=True)
    states = r["states"]
    rows = chip_ticks(b.snd_devices.log, r["t0"], len(states))
    ch_of = chain(s)
    snaps = [sn for v, sp, sn in states]
    out = []
    loops = []
    for ch, pr in ch_of:
        ys = [y for y, (c, p, snd) in states[-1][0].items() if c == ch]
        if ys:                                           # still playing at the cap: a loop
            loop = find_loop(snaps, ys[0], rows, ch)
            if loop is not None:
                a, e = loop
                out.append((ch, pr, -1, [rw[ch] for rw in rows[:e + 1]], a))
                loops.append((ch, a, e))
                continue
            if s not in TEST_SOUNDS:
                raise RuntimeError("sound $%02X channel %d: no end and no loop in %d ticks" % (s, ch, cap))
            print("  sound $%02X channel %d: cut at %d ticks" % (s, ch, cap))
        alive = [k for k, (v, sp, sn) in enumerate(states) if any(c == ch for c, p, snd in v.values())]
        life = alive[-1] + 1 if alive else 0
        audible = [k for k, rw in enumerate(rows) if rw[ch][3]]
        end = max(life, audible[-1] + 1 if audible else 0)
        out.append((ch, pr, life, [rw[ch] for rw in rows[:end]], -1))
    loop = loops or None
    return dict(voices=out, ticks=len(states), loop=loop)


def record_phrase(p):
    """a phrase alone: {pcm (the TMS5220's samples from its first sound to its last), rate, delay (stream samples
    from the command to the first), busy (ticks until the driver may start the next phrase), duck (the mixer value
    while it speaks), duck_ticks}"""
    b = RecBoard()
    r = record_raw([(0, phrase_command(p))], 600, quiet=12, board=b)
    pcm = r["pcm"]
    nz = [i for i, v in enumerate(pcm) if v != -1]
    rate = b.snd_devices.tms.rate
    busy = next((k for k, (v, sp, sn) in enumerate(r["states"]) if not sp), len(r["states"]))
    mix = [(t, v) for t, kind, reg, v in r["log"] if kind == "M"]
    duck = mix[0][1] if mix else None
    duck_ticks = 0
    if len(mix) > 1:
        duck_ticks = (mix[1][0] - r["t0"]) * TICK_HZ // AS + 1
    return dict(pcm=pcm[nz[0]:nz[-1] + 1] if nz else [], rate=rate, delay=nz[0] if nz else 0, busy=busy,
                duck=duck, duck_ticks=duck_ticks, marks=r["rate_marks"])


def _job(a):
    kind, n = a
    return (kind, n, record_sound(n) if kind == "s" else record_phrase(n))


def record_all(build, again=False, sounds=range(SOUNDS), phrases=range(PHRASES), workers=8):
    """every sound and phrase (cached in build/gauntlet/sound_rec.pkl)"""
    path = build / "sound_rec.pkl"
    data = pickle.loads(path.read_bytes()) if path.exists() and not again else {"s": {}, "p": {}}
    todo = [("s", s) for s in sounds if s not in data["s"]] + [("p", p) for p in phrases if p not in data["p"]]
    if todo:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            for kind, n, rec in pool.imap_unordered(_job, todo):
                data[kind][n] = rec
                print("  %s %02X" % ("sound" if kind == "s" else "phrase", n), flush=True)
                path.write_bytes(pickle.dumps(data))
    return data


# ================================================================================================= the STE's streams

# A voice's stream: bytes, each tick one step of the decoder (src/sound_out.s so_step, Stream below):
#   $00-$7F hold n + 1 ticks, $80-$8F volume n (a tick), $90-$9F volume - 1 then hold n & 15 more ticks,
#   $A0-$AF b: tone period (n & 15) << 8 | b, $B1-$B3: mode (1 tone, 2 noise, 3 both), $C0-$DF: noise period n & 31
#   (no tick), $FF the end (the loop, or the voice ends)
S_HOLD, S_VOL, S_DOWN, S_PER, S_MODE, S_NOISE, S_END = 0x00, 0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xFF


def encode_stream(rows, loop=-1):
    """rows [(period, noise period, mode, volume)] -> (bytes, loop offset or -1)"""
    b = bytearray()
    cur = [None, None, None, None]               # the decoder's period, noise, mode, volume
    loop_at = -1
    i = 0
    n = len(rows)

    def same(a, c):
        return a == c or (a[3] == 0 and c[3] == 0)

    while i < n:
        p, q, m, v = rows[i]
        whole = i == loop or cur[0] is None
        if i == loop:
            loop_at = len(b)
        j = i + 1
        while j < n and same(rows[j], rows[i]) and j != loop:
            j += 1
        k = j - i
        if v or whole:
            if whole or (m & 1 and p != cur[0]):
                b += bytes([S_PER | p >> 8, p & 255])
                cur[0] = p
            if whole or (m & 2 and q != cur[1]):
                b.append(S_NOISE | q)
                cur[1] = q
            if whole or (m != cur[2] and v):
                b.append(S_MODE | (m if m else 1))
                cur[2] = m if m else 1
        if whole:
            b.append(S_VOL | v)
            k -= 1
        elif cur[3] is not None and v == cur[3] - 1:
            h = min(k, 16)
            b.append(S_DOWN | (h - 1))
            k -= h
        elif v != cur[3]:
            b.append(S_VOL | v)
            k -= 1
        cur[3] = v
        while k > 0:
            h = min(k, 128)
            b.append(S_HOLD | (h - 1))
            k -= h
        i = j
    b.append(S_END)
    return bytes(b), loop_at


class Stream:
    """the decoder (src/sound_out.s so_step): step() -> (period, noise, mode, volume) or None at the end"""

    def __init__(self, data, loop):
        self.d, self.loop = data, loop
        self.pos = 0
        self.left = 0
        self.per = self.np = self.mode = self.vol = 0

    def step(self):
        if self.left:
            self.left -= 1
            return self.per, self.np, self.mode, self.vol
        d = self.d
        while True:
            c = d[self.pos]
            self.pos += 1
            if c == S_END:
                if self.loop < 0:
                    return None
                self.pos = self.loop
            elif c >= S_NOISE:
                self.np = c & 31
            elif c >= S_MODE:
                self.mode = c & 3
            elif c >= S_PER:
                self.per = (c & 15) << 8 | d[self.pos]
                self.pos += 1
            elif c >= S_DOWN:
                self.vol -= 1
                self.left = c & 15
                return self.per, self.np, self.mode, self.vol
            elif c >= S_VOL:
                self.vol = c & 15
                return self.per, self.np, self.mode, self.vol
            else:
                self.left = c
                return self.per, self.np, self.mode, self.vol


# ================================================================================================= the STE's player

NSLOT = 40                                       # voice slots (live voices and tails)
LIVE_MAX = NVOICES                               # the driver's 30 voices
FOREVER = 0xFFFF
K_NONE, K_STOPALL, K_SOUND, K_KILL, K_FADE, K_FADEPRI, K_SPEECH, K_FLOOR, K_MIXER = range(9)
YM_OFF = [None, -6, -4, -2, -2, -1, 0, 0]       # the mixer's YM2151 gain (0-7) as a YM volume offset (None: mute)
POKEY_OFF = [None, -3, -1, 0]                    # the POKEY's (0-3)
MIX_BOOT = 0xFF                                  # the mixer after the driver's start ($24 | $25)
DEC_LEAD = 128                                   # ADPCM bytes decoded when a phrase starts (256 samples: 41 ms ahead)
DEC_TICK = 64                                    # ... and each tick after (128 samples; the DMA plays 125.2)


def command_table():
    """[(kind, argument)] for the commands 0-$FF"""
    out = []
    for c in range(256):
        t = cmd_type(c) if c < 0xE2 else 0xFF
        a = cmd_arg(c) if c < 0xE2 else 0
        if t == 2:
            out.append((K_STOPALL, 0))
        elif t == 6:
            out.append((K_SOUND, a))
        elif t == 4:
            out.append((K_KILL, sound_of(a)))
        elif t == 8:
            out.append((K_FADE, sound_of(a)))
        elif t == 9:
            out.append((K_FADEPRI, a))
        elif t == 0x0A:
            out.append((K_SPEECH, a))
        elif t == 0:
            out.append((K_FLOOR, (a * 4) & 0xFF))
        elif t == 0x0C:
            out.append((K_MIXER, a))
        else:
            out.append((K_NONE, 0))
    return out


class Voice:
    __slots__ = ("st", "life", "ch", "pri", "snd", "fade", "foff", "on", "row")


class Player:
    """src/sound_out.s in Python: tick(commands) -> the YM2149's registers 0-10 after the tick; also `chans` (the 12
    logical channels' (period, noise, mode, volume) before the mixer's gains) and `speech` (the phrase started this
    tick or None)"""

    def __init__(self, enc):
        """enc: {sounds: {s: [(ch, pri, life, data, loop)]}, phrases: {p: (length, priority, drop, busy, duck)}}"""
        self.enc = enc
        self.cmds = command_table()
        self.slots = [None] * NSLOT
        self.assigned = [-1] * CHANNELS
        self.regs = [0] * 11
        self.regs[7] = 0xFF
        self.floor = 0
        self.mixer = MIX_BOOT
        self.queue = [0] * 8
        self.qhead = self.qtail = 0
        self.cur_pri = 0
        self.busy = 0
        self.duck = 0
        self.duck_mix = MIX_BOOT
        self.speech = None
        self.dec_src = b""
        self.dec_pos = 0
        self.dec_out = []

    def decode(self):
        """the phrase's next bytes into its buffer: DEC_LEAD at its start, DEC_TICK a tick then (6258 Hz: 125.2
        samples a tick)"""
        left = len(self.dec_src) - self.dec_pos
        if left <= 0:
            return
        n = min(left, DEC_LEAD if self.dec_first else DEC_TICK)
        self.dec_first = False
        for b in self.dec_src[self.dec_pos:self.dec_pos + n]:
            for q in (b >> 4, b & 15):
                self.dec_s += adpcm_delta(self.dec_k, q)
                self.dec_k = adpcm_next(self.dec_k, q)
                self.dec_out.append(self.dec_s & 255)
        self.dec_pos += n

    # ---- commands
    def command(self, c):
        kind, a = self.cmds[c]
        sl = self.slots
        if kind == K_SOUND:
            self.start_sound(a)
        elif kind == K_STOPALL:
            self.slots = [None] * NSLOT
            self.qtail = self.qhead
        elif kind == K_KILL:
            for i, v in enumerate(sl):
                if v and v.snd == a:
                    sl[i] = None
        elif kind == K_FADE:
            for v in sl:
                if v and v.snd == a and not v.fade:
                    v.fade = 1
        elif kind == K_FADEPRI:
            for v in sl:
                if v and v.on == 1 and v.pri == a and not v.fade:
                    v.fade = 1
        elif kind == K_SPEECH:
            self.speak(a)
        elif kind == K_FLOOR:
            self.floor = a
        elif kind == K_MIXER:
            self.mixer = a

    def start_sound(self, s):
        sl = self.slots
        for ch, pri, life, data, loop in self.enc["sounds"][s]:
            live = sum(1 for v in sl if v and v.on == 1)
            if live >= LIVE_MAX:
                low = None
                for i, v in enumerate(sl):
                    if v and v.on == 1 and v.ch == ch and (low is None or v.pri < sl[low].pri):
                        low = i
                if low is None or pri < sl[low].pri:
                    return
                sl[low] = None
            for i, v in enumerate(sl):
                if v and v.ch == ch and (v.on != 1 or v.pri == pri):
                    sl[i] = None
            free = next((i for i, v in enumerate(sl) if v is None), None)
            if free is None:
                return
            v = Voice()
            v.st = Stream(data, loop)
            v.life, v.ch, v.pri, v.snd = life, ch, pri, s
            v.fade = v.foff = 0
            v.on = 1
            sl[free] = v

    def speak(self, p):
        length, pri, drop, busy, duck = self.enc["phrases"][p]
        if pri < self.floor:
            return
        if not self.busy:
            self.start_phrase(p)
            return
        y = (self.qhead + 1) & 7
        if y == self.qtail or pri < self.cur_pri:
            return
        if pri > self.cur_pri:
            self.qtail = self.qhead
        self.cur_pri = pri
        self.qhead = y
        self.queue[y] = p

    def start_phrase(self, p):
        length, pri, drop, busy, duck = self.enc["phrases"][p]
        self.dec_src = self.enc["pcm"][p]
        self.dec_pos = 0
        self.dec_first = True
        self.dec_k = self.dec_s = 0
        self.dec_out = []
        self.cur_pri = pri
        self.busy = busy
        self.duck = duck
        base = self.mixer
        ym = max(0, (base & 7) - (drop >> 1))
        pk = max(0, ((base >> 3) & 3) - (drop >> 2))
        self.duck_mix = (base & 0xE0) | pk << 3 | ym
        self.speech = p

    def speech_tick(self):
        if self.duck:
            self.duck -= 1
        if self.busy:
            self.busy -= 1
            if not self.busy:
                if self.qtail != self.qhead:
                    self.qtail = (self.qtail + 1) & 7
                    self.start_phrase(self.queue[self.qtail])
                else:
                    self.cur_pri = 0

    # ---- a tick
    def tick(self, cmds=()):
        self.speech = None
        self.speech_tick()
        for c in cmds:
            self.command(c)
        sl = self.slots
        for i, v in enumerate(sl):
            if v is None:
                continue
            r = v.st.step()
            if r is None:
                sl[i] = None
                continue
            if v.fade:
                if v.fade == FADE_STEP:
                    v.fade = 1
                    v.foff += 1
                    if v.foff >= FADE_END:
                        sl[i] = None
                        continue
                else:
                    v.fade += 1
            v.row = r
            if v.on == 1 and v.life != FOREVER:
                if v.life == 0:
                    v.on = 3
                else:
                    v.life -= 1
        best = [-1] * CHANNELS
        bkey = [-1] * CHANNELS
        for i, v in enumerate(sl):
            if v is None:
                continue
            key = v.pri + 1 if v.on == 1 else 0
            if key > bkey[v.ch]:
                bkey[v.ch], best[v.ch] = key, i
        for i, v in enumerate(sl):
            if v is not None and v.on == 3:
                if bkey[v.ch] > 0:
                    sl[i] = None
                    if best[v.ch] == i:                  # (cannot be: a live voice won)
                        best[v.ch] = -1
                else:
                    v.on = 2
        chans = []
        for c in range(CHANNELS):
            if best[c] < 0:
                chans.append((0, 0, 0, 0))
            else:
                v = sl[best[c]]
                p, q, m, vol = v.row
                if v.pri * 4 + 1 < self.floor:     # the floor ($01: only priorities from 60 on; a tail too)
                    vol = 0
                chans.append((p, q, m, max(0, vol - v.foff)))
        self.chans = chans
        r = self.mix(chans)
        self.decode()
        return r

    def gains(self):
        mx = self.duck_mix if self.duck else self.mixer
        return YM_OFF[mx & 7], POKEY_OFF[(mx >> 3) & 3]

    def mix(self, chans):
        ym, pk = self.gains()
        vals = []
        for c, (p, q, m, v) in enumerate(chans):
            off = pk if c < 4 else ym
            v = 0 if off is None or not m else max(0, v + off)
            vals.append((p, q, m, v))
        cand = [c for c in range(CHANNELS) if vals[c][3]]
        key = lambda c: vals[c][3] * 2 + (self.assigned[c] >= 0)
        picked = sorted(cand, key=lambda c: (-key(c), c))[:3]
        new = [-1] * CHANNELS
        out = [None] * 3
        for c in picked:
            if self.assigned[c] >= 0:
                out[self.assigned[c]] = c
                new[c] = self.assigned[c]
        for c in picked:
            if new[c] < 0:
                k = out.index(None)
                out[k] = c
                new[c] = k
        self.assigned = new
        r = self.regs
        mixbits = 0x3F
        nbest = None
        for k in range(3):
            c = out[k]
            if c is None:
                r[8 + k] = 0
                continue
            p, q, m, v = vals[c]
            r[8 + k] = v
            if m & 1:
                r[2 * k], r[2 * k + 1] = p & 255, p >> 8
                mixbits &= ~(1 << k)
            if m & 2:
                mixbits &= ~(8 << k)
                if nbest is None or v > nbest[0]:
                    nbest = (v, q)
        if nbest:
            r[6] = nbest[1]
        r[7] = 0xC0 | mixbits
        return list(r)


# ================================================================================================= the STE's data

SPEECH_SHIFT = 8                                 # the TMS5220's 16-bit samples -> the DMA's signed bytes


def resample(x, rate, to=STE_PCM_HZ):
    """band-limited (FFT) resampling"""
    n = len(x)
    if n == 0:
        return np.zeros(0)
    m = max(1, int(round(n * to / rate)))
    X = np.fft.rfft(x)
    k = min(len(X), m // 2 + 1)
    Y = np.zeros(m // 2 + 1, complex)
    Y[:k] = X[:k]
    return np.fft.irfft(Y, m) * (m / n)


def phrase_pcm(rec):
    """a phrase's samples for the DMA sound: 6258 Hz, signed bytes, an even count"""
    x = np.array(rec["pcm"], float)
    x[x == -1] = 0
    y = resample(x, rec["rate"])
    b = np.clip(np.round(y / (1 << SPEECH_SHIFT)), -128, 127).astype(np.int8).tobytes()
    return b + bytes(len(b) & 1)


# The speech as 4-bit ADPCM (half the bytes of 8-bit PCM; the runtime has to end below the renderer's buffers at
# $200000): a byte = two samples (the high nibble first), the 8-bit sample + delta[state][nibble] (the encoder never
# lets it wrap), the state then index[nibble & 7] steps on (IMA's rule).  The STE decodes a whole byte through one
# table entry (state, byte) -> (delta 1, delta 2, the next state << 8): adpcm_table, ADPCM_STATES x 256 x 4 bytes.
ADPCM_STEPS = [max(1, round(1.2 ** k)) for k in range(24)]
ADPCM_STATES = len(ADPCM_STEPS)
ADPCM_INDEX = [-1, -1, -1, -1, 2, 4, 6, 8]


def adpcm_delta(k, n):
    m = n & 7
    d = int((m + 0.25) * ADPCM_STEPS[k] + 0.5)
    return -d if n & 8 else d


def adpcm_next(k, n):
    return max(0, min(ADPCM_STATES - 1, k + ADPCM_INDEX[n & 7]))


def adpcm_table():
    """(state << 8 | byte) * 4 -> delta 1, delta 2 (signed bytes), the next state << 8 (word)"""
    out = bytearray()
    for k in range(ADPCM_STATES):
        for b in range(256):
            n1, n2 = b >> 4, b & 15
            k1 = adpcm_next(k, n1)
            out += bytes([adpcm_delta(k, n1) & 255, adpcm_delta(k1, n2) & 255]) + (adpcm_next(k1, n2) << 8).to_bytes(2, "big")
    return bytes(out)


def adpcm_encode(x):
    """signed 8-bit samples (an even count) -> bytes: each nibble the one closest to the sample that keeps the
    decoder's byte in range"""
    deltas = [[adpcm_delta(k, n) for n in range(16)] for k in range(ADPCM_STATES)]
    nxt = [[adpcm_next(k, n) for n in range(16)] for k in range(ADPCM_STATES)]
    out = bytearray()
    sv, k = 0, 0
    hi = None
    for t in x:
        t = int(t)
        best = None
        dk = deltas[k]
        for n in range(16):
            v = sv + dk[n]
            if -128 <= v <= 127:
                e = abs(t - v)
                if best is None or e < best[0]:
                    best = (e, n, v)
        e, n, sv = best
        k = nxt[k][n]
        if hi is None:
            hi = n
        else:
            out.append(hi << 4 | n)
            hi = None
    return bytes(out)


def adpcm_decode(data, k=0, sv=0):
    """bytes -> signed 8-bit samples (the STE's decoder)"""
    out = []
    for b in data:
        for n in (b >> 4, b & 15):
            sv += adpcm_delta(k, n)
            k = adpcm_next(k, n)
            out.append(sv)
    return out


def encode_all(data):
    """the recordings -> {sounds: {s: [(ch, pri, life, stream, loop)]}, phrases: {p: (ADPCM bytes, pri, drop, busy,
    duck)}, pcm: {p: the ADPCM bytes}}"""
    sounds = {}
    for s, rec in sorted(data["s"].items()):
        vs = []
        for ch, pr, life, rows, loop in rec["voices"]:
            st, lp = encode_stream(rows or [(0, 0, 0, 0)], loop)
            vs.append((ch, pr, FOREVER if life < 0 else min(life, FOREVER - 1), st, lp))
        sounds[s] = vs
    phrases, pcm = {}, {}
    for p, rec in sorted(data["p"].items()):
        pri, squeak, drop = phrase_info(p)
        x = np.frombuffer(phrase_pcm(rec), np.int8)
        pcm[p] = adpcm_encode(x)
        phrases[p] = (len(pcm[p]), pri, drop, rec["busy"], rec["duck_ticks"])
    return dict(sounds=sounds, phrases=phrases, pcm=pcm)


def emit(build, enc):
    """build/gauntlet/sound_data.s (included by src/sound_out.s) and gauntlet_speech.bin; returns the sizes"""
    L = ["; generated by tools/sound.py: the sound commands, sounds, voices' streams and phrases for src/sound_out.s",
         "\teven", "so_cmds:"]
    cmds = command_table()
    for i in range(0, 256, 16):
        L.append("\tdc.b\t" + ",".join("%d,%d" % c for c in cmds[i:i + 16]))
    L.append("so_sounds:")
    for s in range(SOUNDS):
        L.append("\tdc.l\tso_s%02X" % s)
    L.append("so_phrases:")
    off = 0
    for p in range(PHRASES):
        n, pri, drop, busy, duck = enc["phrases"][p]
        L.append("\tdc.l\tso_pcm+%d,%d\n\tdc.b\t%d,%d\n\tdc.w\t%d,%d,0" % (off, n, pri, drop, busy, duck))
        off += n
    size = 0
    streams = []
    for s in range(SOUNDS):
        vs = enc["sounds"][s]
        L.append("so_s%02X:\tdc.w\t%d" % (s, len(vs)))
        for k, (ch, pr, life, st, lp) in enumerate(vs):
            lab = "so_s%02X_%d" % (s, k)
            L.append("\tdc.b\t%d,%d\n\tdc.w\t%d\n\tdc.l\t%s,%s" % (ch, pr, life, lab, "%s+%d" % (lab, lp) if lp >= 0 else "0"))
            streams.append((lab, st))
    for lab, st in streams:
        L.append(lab + ":")
        for i in range(0, len(st), 32):
            L.append("\tdc.b\t" + ",".join(str(x) for x in st[i:i + 32]))
        size += len(st)
    L += ["\teven", "so_pcm:\tincbin\t\"gauntlet_speech.bin\"", "\teven",
          "so_adpcm:\tincbin\t\"gauntlet_adpcm.bin\"\t; (state << 8 | byte) * 4: delta 1, delta 2, next state << 8",
          "SO_SPBUF = %d\t\t\t; the longest phrase's samples" % (2 * max(n for n, *r in enc["phrases"].values()))]
    (build / "sound_data.s").write_text("\n".join(L) + "\n")
    pcm = b"".join(enc["pcm"][p] for p in range(PHRASES))
    (build / "gauntlet_speech.bin").write_bytes(pcm)
    tab = adpcm_table()
    (build / "gauntlet_adpcm.bin").write_bytes(tab)
    tables = 512 + 4 * SOUNDS + 16 * PHRASES + sum(2 + 12 * len(v) for v in enc["sounds"].values()) + len(tab)
    return dict(streams=size, tables=tables, speech=len(pcm), buffer=2 * max(n for n, *r in enc["phrases"].values()))


def build(build_dir_, again=False):
    data = record_all(build_dir_, again)
    enc = encode_all(data)
    sizes = emit(build_dir_, enc)
    print("sound: streams %d bytes, tables %d, speech %d (ADPCM: %.1f s at %d Hz), the phrase buffer %d (bss)" % (
        sizes["streams"], sizes["tables"], sizes["speech"], 2 * sizes["speech"] / STE_PCM_HZ, STE_PCM_HZ,
        sizes["buffer"]))
    return enc


if __name__ == "__main__":
    from paths import build_dir
    build(build_dir("gauntlet"), again="--again" in sys.argv)
