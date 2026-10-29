"""Track & Field / Hyper Sports: the sound board's Z80 driver translated to 68000 code (engine/z80x.py), and the data the
player (src/sound.s) needs.  Shared by both ports (tools/sound.py GAMES).

    from sndgen import build; report = build('trackfld')   -> build/<game>/snd_code.s, snd_data.s, snd_pcm.bin

The rendered samples (snd_pcm.bin, snd_pcm_index.txt), the tunes' measured effects (tunes.txt) and the phrases' busy
times (vlm_busy.txt) are cached in build/<game>/: delete them to render them again.

Labels X<pc>, the dispatch table snd_dispatch_sw, the register map of z80x.FAST (d0 A, d1 BC (byte-swapped), d2 DE,
d3 HL, d4 IX, a2 IY, d6 the flags, a5 SP, a6 the sound CPU's 64 KB block, a4 the table); src/sound.s saves the main
program's registers around it.

The board's chips are memory-mapped (tools/sound.py Board): the static `ld (nn),a` / `ld a,(nn)` of the I/O become
(SEmitter.x_ld): the SN latch (snd_snl), the SN strobe (bsr snd_sn_w: the latched byte into the register file), the
VLM's data byte (snd_vlm_data), the command latch (snd_cmd), BSY (bsr snd_bsy: Track & Field $10, Hyper Sports 4 with
the timer's bits 0 as the waits are left out), the timer (0: read only in the waits, which the schedule leaves out);
the DAC's stores are dropped (its pulses outside the tunes are left out: README).  The VLM's pins are stores through
HL (`ld (hl),a` with HL from RAM): the sites the coverage saw store there call snd_vlm_pins with the address.  Any
other I/O access stops the build (the coverage's io).  The tune routine at TUNE is a native (snd_tune: its measured
effect, tools/sound.py tunes()); LOOP is the hook (snd_hook: the next tick or the end of the run).
"""
from pathlib import Path
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from sound import GAMES, TOKEN, TICK_FX, SAMPLE_FX, HALF, VTAB, ym_period, ym_noise, busy_table, tunes, tune_render
from sound import CLOCK, SN_CLOCK
from paths import build_dir, require_coverage

ROM_END = 0x4000
DMA_RATE = 12517                          # the STE's DMA sound: 12517 Hz, 8 bits mono
IO = {}                                   # the game's I/O map (set by build): address -> kind


def io_kind(game, a, rw):
    """an I/O address -> 'latch' 'timer' 'bsy' 'snl' 'sns' 'data' 'pins' 'dac' 'nop', or None (RAM, ROM)"""
    if a < 0x5000 or game == 'trackfld' and a < 0x6000:
        return None
    if game == 'hyperspt':
        return {(0x6000, 'r'): 'latch', (0x8000, 'r'): 'bsy', (0xA000, 'w'): 'data', (0xE000, 'w'): 'dac',
                (0xE001, 'w'): 'snl', (0xE002, 'w'): 'sns'}.get((a, rw), 'pins' if 0xC000 <= a < 0xE000 and rw == 'w'
                                                                else 'bad')
    if a < 0x8000:
        return 'latch' if rw == 'r' else 'bad'
    if a < 0xA000:
        return 'timer' if rw == 'r' else 'bad'
    if a < 0xC000:
        return 'snl' if rw == 'w' else 'bad'
    if a < 0xE000:
        return 'sns' if rw == 'w' else 'bad'
    k = a & 7
    if rw == 'r':
        return 'bsy' if k == 2 else 'bad'
    return {0: 'dac', 1: 'nop', 3: 'pins', 4: 'data'}.get(k, 'bad')


class SEmitter(z80x.Emitter):
    game = 'trackfld'
    pin_sites = set()                         # pcs of `ld (hl),a` that set the VLM's pins

    def x_ld(self, ins):
        dst, src = ins.ops
        g = self.game
        if dst[0] == 'ind16' and io_kind(g, dst[1], 'w'):
            k = io_kind(g, dst[1], 'w')
            if src != ('r8', 'a') or k == 'bad':
                raise z80x.Unsupported('I/O store ' + ins.text)
            if k == 'snl':
                self.e('move.b d0,snd_snl')
            elif k == 'sns':
                self.e('bsr snd_sn_w')
            elif k == 'data':
                self.e('move.b d0,snd_vlm_data')
            elif k == 'pins':
                self.e('move.w #$%04X,d7' % dst[1])
                self.e('bsr snd_vlm_pins')
            return                                # (dac, nop: nothing)
        if src[0] == 'ind16' and io_kind(g, src[1], 'r'):
            k = io_kind(g, src[1], 'r')
            if dst != ('r8', 'a') or k == 'bad':
                raise z80x.Unsupported('I/O load ' + ins.text)
            if k == 'latch':
                self.e('move.b snd_cmd,d0')
            elif k == 'timer':
                self.e('moveq #0,d0')
            else:
                self.e('bsr snd_bsy')            # (d0: BSY as the game's port shows it)
            return
        if dst == ('ind', 'hl', 0) and ins.pc in self.pin_sites:
            if src != ('r8', 'a'):
                raise z80x.Unsupported('VLM pins ' + ins.text)
            self.e('move.w d3,d7')
            self.e('bsr snd_vlm_pins')
            return
        z80x.Emitter.x_ld(self, ins)

    # the `add a,a ... jp (hl)` jump table (rst $10), emitted at its calls (Pooyan's sndgen)
    helper = {}

    def table_jump(self, base):
        """HL = the word at base + 2 (A & $7F), A = its low byte, S, Z and C clear, a jump there (snd_jt<base>)"""
        self.e('moveq #$7F,d7')
        self.e('and.b d0,d7')
        self.e('lsl.w #3,d7')
        self.e('lea snd_jt%04X,a0' % base)
        self.e('move.w 4(a0,d7.w),d3')
        self.e('move.b d3,d0')
        self.e('clr.b d6')
        self.e('move.l (a0,d7.w),a0')
        self.e('jmp (a0)')

    def x_rst(self, ins):
        h = self.helper.get(ins.ops[0][1])
        if h is None:
            return z80x.Emitter.x_rst(self, ins)
        self.push_ret(ins.pc + ins.length)
        self.table_jump(h[2][ins.pc])

    def x_call(self, ins):
        h = self.helper.get(ins.target) if ins.ops[0][0] == 'addr' else None
        if h is None:
            return z80x.Emitter.x_call(self, ins)
        self.push_ret(ins.pc + ins.length)
        self.table_jump(h[2][ins.pc])

    def x_jp(self, ins):
        h = self.helper.get(ins.ops[0][1]) if ins.ops[0][0] == 'addr' else None
        if h is None:
            return z80x.Emitter.x_jp(self, ins)
        self.table_jump(h[2][ins.pc])

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)


def helpers(code, live_in, jumps):
    """the `add a,a; add a,l; ... jp (hl)` table every caller enters after `ld hl,nn` (nn $0100-$7DFF: the `adc a,0`
    leaves S, Z and C clear) and whose targets read no other flags: pc -> ('table', ret pc, {caller: nn})"""
    def seq(pc, n):
        out = []
        for _ in range(n):
            ins = code.get(pc)
            if ins is None:
                return None
            out.append(ins)
            pc += ins.length
        return out
    out = {}
    entered = {i.target for i in code.values()} | set(jumps)
    flags_ok = all(live_in.get(t, 0) & ~z80x.CCRF == 0 for t in jumps)
    pattern = ['add a,a', 'add a,l', 'ld l,a', 'ld a,h', 'adc a,$00', 'ld h,a', 'ld a,(hl)', 'inc hl', 'ld h,(hl)',
               'ld l,a', 'jp (hl)']
    for pc in code:
        s = seq(pc, len(pattern))
        if not (s and [i.text for i in s] == pattern and flags_ok):
            continue
        callers = [c for c, i in code.items() if i.target == pc and i.flow in ('rst', 'call', 'jmp', 'ccall', 'jcc')]
        before = [next((i for i in code.values() if i.pc + i.length == c), None) for c in callers]
        if callers and all(b is not None and b.mn == 'ld' and b.ops[0] == ('r16', 'hl') and b.ops[1][0] == 'imm'
                           and 0x0100 <= b.ops[1][1] < 0x7E00 for b in before) \
                and all(code[c].flow in ('rst', 'call', 'jmp') and code[c].mn in ('rst', 'call', 'jp')
                        and len(code[c].ops) == 1 and c not in entered for c in callers):
            out[pc] = ('table', s[-1].pc, {c: b.ops[1][1] for c, b in zip(callers, before)})
    return out


def jump_tables(rom_img, em):
    labels = {p: 'X%04X' % p for p in em.code if p not in em.no_entry}
    bases = sorted({b for h in SEmitter.helper.values() for b in h[2].values()})
    rows = ['\tcnop 0,4']
    for base in bases:
        rows.append('snd_jt%04X:' % base)
        for i in range(128):
            t = rom_img[base + 2 * i] | rom_img[base + 2 * i + 1] << 8
            rows.append('\tdc.l %s\n\tdc.w $%04X,0' % (labels.get(t, 'snd_badpc'), t))
    return rows


def coverage(game):
    require_coverage(game, ['cover_sound101.pkl'])
    pcs, jumps, io = set(), set(), set()
    for f in sorted(build_dir(game).glob('cover_sound*.pkl')):
        d = pickle.loads(f.read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        io |= d.get('io', set())
    return {p for p in pcs if p < ROM_END}, {j for j in jumps if j < ROM_END}, io


def check_io(game, code, io):
    """every I/O access the coverage saw is a static `ld (nn),a` / `ld a,(nn)` or a pin store `ld (hl),a` -> the
    pin sites"""
    pins = set()
    for pc, a, rw in sorted(io):
        k = io_kind(game, a, rw)
        if k is None:
            continue
        ins = code.get(pc)
        if ins is None or k == 'bad':
            raise RuntimeError('I/O access %s %04X by %04X %s' % (rw, a, pc, ins.text if ins else '?'))
        if ins.text == 'ld (hl),a' and k == 'pins':
            pins.add(pc)
        elif ins.mn != 'ld' or ('ind16', a) not in ins.ops or ('r8', 'a') not in ins.ops:
            raise RuntimeError('I/O access %s %04X by %04X %s' % (rw, a, pc, ins.text))
    return pins


def image(game):
    r = GAMES[game].rom()
    return r + bytes(0x10000 - len(r))


def translate(game):
    g = GAMES[game]
    rom_img = image(game)
    pcs, jumps, io = coverage(game)
    roots = {0, 0x38, g.loop, g.tick} | jumps
    cache = {}
    while True:
        code, tables = discover.discover(rom_img, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom_img, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    SEmitter.game = game
    SEmitter.pin_sites = check_io(game, code, io)
    SEmitter.helper = {}
    cfg = z80x.Config(prefix='X', table='snd_dispatch', token_sym='snd_token_ret', mode='signed', block=0x10000,
                      iyaddr=0x5FF0, fshadow=0x5FF2, io_read_redirect={}, write_hooks=[], nmi_token=TOKEN,
                      table_entries=0x10000, rst28_tables=False, hl_tables=True, bit_s=False, inline_leaves=6,
                      inline_limit=ROM_END, inline_rst=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    natives = {g.tune: 'snd_tune', g.tick: 'snd_idle'}   # (src/sound.s: the tune's effect; an idle tick at once)
    if game == 'hyperspt':
        natives.update({0x0E76: 'snd_note1', 0x0E7E: 'snd_note2', 0x0E86: 'snd_note3'})   # (src/sound.s snd_note)
    kw = dict(emitter=SEmitter, ijmp_flags=True, flags_at={g.loop}, natives=natives)
    em = compile_code(code, joins, cfg, {g.loop}, **kw)
    SEmitter.helper = helpers(code, em.live_in, jumps)
    em = compile_code(code, joins, cfg, {g.loop}, **kw)
    out = ['; generated: %s sound Z80 -> 68000 (games/trackfld/tools/sndgen.py)' % game, '\tsection text,code']
    out += [l.replace('z80_hook', 'snd_hook').replace('z80_badpc', 'snd_badpc').replace('z80_rnd', 'snd_badpc')
            .replace('z80_unsupported', 'snd_badpc') for l in em.lines]
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['X%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp snd_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em, TICK_TOKENS if game == 'hyperspt' else {}) + \
           jump_tables(rom_img, em)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed sound instructions cannot be translated: %s' % seen)
    report = {'instructions': len(code), 'coverage': len(pcs), 'pin_sites': ['%04X' % p for p in sorted(SEmitter.pin_sites)],
              'helpers': {'%04X' % k: v[0] for k, v in sorted(SEmitter.helper.items())}, 'unsupported': em.unsupported,
              'missing': ['%04X' % p for p in missing]}
    return '\n'.join(out) + '\n', report


# Hyper Sports' native tick (src/sound.s snd_tick) enters the translated code with these return addresses on the Z80
# stack (the driver never uses them: no ROM, RAM or I/O there); their dispatch entries are its continuations.
TICK_TOKENS = {0xFFE0: 'snd_tk1', 0xFFE2: 'snd_tk2', 0xFFE4: 'snd_tk3', 0xFFE6: 'snd_tk4', 0xFFE8: 'snd_tk5',
               0xFFEA: 'snd_tk6'}


def dispatch_table(code, em, extra=None):
    labels = {p: 'X%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'snd_token_ret'
    for a, label in (extra or {}).items():
        assert a not in labels, '%04X' % a
        labels[a] = label
    rows, run = ['\tcnop 0,4', 'snd_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,snd_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,snd_badpc' % run)
    return rows


# ---- the DMA's samples ---------------------------------------------------------------------------------------------

def resample(x, rate_in, rate_out):
    """linear interpolation"""
    import numpy as np
    x = np.asarray(x, dtype=np.float64)
    n = int(len(x) * rate_out / rate_in)
    t = np.arange(n) * (rate_in / rate_out)
    return np.interp(t, np.arange(len(x)), x)


def phrases(game):
    """data byte -> float samples at DMA_RATE: every phrase of the VLM ROM's indirect table (the even bytes below the
    first phrase's address)"""
    from vlm5030 import phrase, RATE
    rom = GAMES[game].vlm_rom()
    first = rom[0] << 8 | rom[1]
    out = {}
    for d in range(0, min(first, 256), 2):
        s, n = phrase(rom, d)
        while s and s[-1] == 0:
            s.pop()
        if s and max(map(abs, s)):
            out[d] = resample(s, RATE, DMA_RATE)
    return out


def sn_render(log, cycles, start_regs=None):
    """the SN76489A (MAME sn76496.cpp: counters at clock / 16, 2 dB volume steps, the 17-bit noise LFSR, taps 1 and 2
    of $04 / $08... as sn76489a: feedback $10000, taps $04 $08) driven by log [(cycle, byte)] for `cycles` Z80
    cycles -> float samples at SN_CLOCK / 16 (MAME's units: 0..1 a channel x 4)"""
    import numpy as np
    step = 32                                # Z80 cycles a counter step (3579545 / (1789772 / 16))
    n = cycles // step + 1
    vol = [0.25 * 10 ** (-2 * a / 20) if a < 15 else 0.0 for a in range(16)]
    reg = list(start_regs or [0, 15, 0, 15, 0, 15, 0, 15])
    period = [r or 0x400 for r in (reg[0], reg[2], reg[4])] + [0]
    count = [0, 0, 0, 0]
    output = [0, 0, 0, 0]
    rng = 0x10000
    latch = 0
    out = np.zeros(n)
    k = 0
    events = list(log) + [(cycles + step, None)]

    def noise_period():
        return period[2] << 1 if reg[6] & 3 == 3 else 1 << (5 + (reg[6] & 3))
    period[3] = noise_period()
    t = 0
    for cy, v in events:
        end = min(n, cy // step)
        while t < end:
            # whole steps until the next write: tones analytically would be faster; this is offline
            for i in range(3):
                count[i] -= 1
                if count[i] <= 0:
                    output[i] ^= 1
                    count[i] = period[i]
            count[3] -= 1
            if count[3] <= 0:
                fb = ((rng & 4) != 0) != ((rng & 8) != 0 and bool(reg[6] & 4))
                rng = (rng >> 1) | (0x10000 if fb else 0)
                output[3] = rng & 1
                count[3] = period[3]
            out[t] = sum(vol[reg[2 * i + 1] & 15] for i in range(4) if output[i])
            t += 1
        if v is None:
            break
        if v & 0x80:
            latch = (v >> 4) & 7
            reg[latch] = (reg[latch] & 0x3F0) | (v & 0x0F)
        r = latch
        if r in (0, 2, 4):
            if not v & 0x80:
                reg[r] = (reg[r] & 0x0F) | ((v & 0x3F) << 4)
            period[r // 2] = reg[r] or 0x400
            if r == 4 and reg[6] & 3 == 3:
                period[3] = period[2] << 1
        elif r == 6:
            if not v & 0x80:
                reg[r] = (reg[r] & 0x3F0) | (v & 0x0F)
            period[3] = noise_period()
            rng = 0x10000
        elif not v & 0x80:
            reg[r] = (reg[r] & 0x3F0) | (v & 0x0F)
    return out


def tune_samples(game, r):
    """a tune's sound (tools/sound.py tune_render's SN and DAC logs) at DMA_RATE: MAME's mix (the SN x 1.0, the DAC x
    0.4: -1..1 from its byte), the DC taken out"""
    import numpy as np
    sn = sn_render(r['sn'], r['cycles'])
    rate = SN_CLOCK / 16
    t = np.arange(len(sn)) * 32
    dac = np.zeros(len(sn))
    last, lv = 0, 0.0
    for cy, v in r['dac']:
        k = min(len(sn), cy // 32)
        dac[last:k] = lv
        last, lv = k, (v / 255 * 2 - 1) * 0.4
    dac[last:] = lv
    x = sn + dac
    # box filter to the DMA's rate
    m = int(len(x) * DMA_RATE / rate)
    edges = (np.arange(m + 1) * (rate / DMA_RATE)).astype(int)
    cs = np.concatenate([[0], np.cumsum(x)])
    y = (cs[edges[1:]] - cs[edges[:-1]]) / np.maximum(1, edges[1:] - edges[:-1])
    y -= y.mean()
    return y


def pcm(game):
    """-> (bytes of the DMA's samples, {('phrase', d) / ('tune', i): (offset, length)}): signed 8-bit, each even; the
    phrases scaled together (their loudest to ~100), the tunes together (~100)"""
    import numpy as np
    parts = {}
    ph = phrases(game)
    peak = max(np.abs(s).max() for s in ph.values())
    for d, s in ph.items():
        parts[('phrase', d)] = s * (100 / peak)
    tr = tune_render(game)
    ts = {i: tune_samples(game, r) for i, r in tr.items()}
    peak = max(np.abs(s).max() for s in ts.values())
    for i, s in ts.items():
        parts[('tune', i)] = s * (100 / peak)
    blob = bytearray()
    index = {}
    for key in sorted(parts):
        b = np.clip(np.round(parts[key]), -128, 127).astype(np.int8).tobytes()
        if len(b) & 1:
            b += b'\0'
        index[key] = (len(blob), len(b))
        blob += b
    return bytes(blob), index


def data(game, index):
    """snd_data.s: the schedule's constants, the YM's tables, the phrases' busy times and samples, the tunes"""
    g = GAMES[game]
    busy = busy_table(game)
    tfx = tunes(game)
    out = ['; generated: %s sound data (games/trackfld/tools/sndgen.py)' % game,
           'SND_FRAME_FX = %d\t\t; an arcade frame (half Z80 cycles)' % g.frame_fx,
           'SND_TICK_FX = %d\t\t; a tick: 4096 cycles' % TICK_FX,
           'SND_LOOP_SW = $%04X\t\t; the loop\'s head $%04X, byte swapped' % (((g.loop & 255) << 8) | (g.loop >> 8), g.loop),
           'SND_HS = %d' % (game == 'hyperspt'),
           'SND_FAST = $%04X' % (g.fast or 0),
           'SND_PIN_ST = %d\nSND_PIN_RST = %d' % ((4, 5) if game == 'hyperspt' else (8, 9)),
           'SND_BSY_BIT = %d' % (2 if game == 'hyperspt' else 4),
           'snd_loop_label = X%04X' % g.loop, 'snd_tick_label = X%04X' % g.tick,
           '\tsection data,data', '\teven']
    out.append('snd_ptab:\t; SN tone period -> YM period')
    vals = [ym_period(n) for n in range(1024)]
    for i in range(0, 1024, 16):
        out.append('\tdc.w ' + ','.join('%d' % v for v in vals[i:i + 16]))
    out.append('snd_ntab:\t; tone 2 period & 15 -> the YM noise period (noise mode 3, period < 16)')
    out.append('\tdc.b ' + ','.join('%d' % ym_noise(3, n) for n in range(16)))
    out.append('snd_vtab:\tdc.b ' + ','.join(map(str, VTAB)))
    out.append('\teven\nsnd_busy_tab:\t; VLM data byte -> BSY time (half cycles)')
    for i in range(0, 256, 8):
        out.append('\tdc.l ' + ','.join('%d' % (busy[d] * SAMPLE_FX) for d in range(i, i + 8)))
    out.append('snd_phr_tab:\t; VLM data byte -> its samples (offset in snd_pcm, length; 0: none)')
    for d in range(256):
        o, n = index.get(('phrase', d), (0, 0))
        out.append('\tdc.l %d,%d' % (o, n))
    out.append('snd_tune_tab:\t; the tunes: time (half cycles), samples (offset, length), RAM, SN bytes, VLM reset byte')
    for i in sorted(tfx):
        out.append('\tdc.l snd_tune%d' % i)
    out.append('SND_TUNES = %d' % len(tfx))
    for i, (units, ram, sn, vlm) in sorted(tfx.items()):
        o, n = index[('tune', i)]
        out.append('snd_tune%d:\tdc.l %d,%d,%d' % (i, units, o, n))
        out.append('\tdc.w %d\t; RAM bytes' % len(ram))
        for a, v in ram:
            out.append('\tdc.w $%04X,$%02X' % (a, v))
        out.append('\tdc.w %d\t; SN bytes' % len(sn))
        if sn:
            out.append('\tdc.w ' + ','.join('$%02X' % v for v in sn))
        out.append('\tdc.w %d\t; the VLM reset: the data byte latched' % (vlm[0] if vlm else -1))
    out += ['\tcnop 0,4', 'snd_pcm:\tincbin "snd_pcm.bin"', '\teven']
    return '\n'.join(out) + '\n'


def build(game, report_file=None):
    text, report = translate(game)
    bd = build_dir(game)
    (bd / 'snd_code.s').write_text(text)
    (bd / 'snd.rom').write_bytes(image(game)[:0x4000])
    pc = bd / 'snd_pcm.bin'
    idx = bd / 'snd_pcm_index.txt'
    if not pc.exists() or not idx.exists():
        blob, index = pcm(game)
        pc.write_bytes(blob)
        idx.write_text(''.join('%s %d %d %d\n' % (k[0], k[1], o, n) for k, (o, n) in sorted(index.items())))
    index = {}
    for line in idx.read_text().splitlines():
        k, i, o, n = line.split()
        index[(k, int(i))] = (int(o), int(n))
    (bd / 'snd_data.s').write_text(data(game, index))
    report['pcm_bytes'] = pc.stat().st_size
    return report


if __name__ == '__main__':
    game = sys.argv[1] if len(sys.argv) > 1 else 'trackfld'
    rep = build(game)
    print({k: v for k, v in rep.items() if k not in ('unsupported',)}, len(rep['unsupported']), 'unsupported')
