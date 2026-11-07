"""Mikie's sound board's Z80 driver translated to 68000 code (engine/z80x.py), and the data the player (src/sound.s)
needs.  After games/trackfld/tools/sndgen.py (the same family of drivers), without speech, DAC and tunes.

    from sndgen import build; report = build()   -> build/mikie/snd_code.s, snd_data.s, snd.rom

Labels X<pc>, the dispatch table snd_dispatch_sw, the register map of z80x.FAST (d0 A, d1 BC (byte-swapped), d2 DE,
d3 HL, d4 IX, a2 IY, d6 the flags, a5 SP, a6 the sound CPU's 64 KB block, a4 the table); src/sound.s saves the main
program's registers around it.

The chips' stores are static `ld (nn),a`: $8002 / $8004 write the SN chips (bsr snd_sn1_w / snd_sn2_w: the byte in d0),
$8000, $8001, $8079 and $A003 are dropped; the loads: $8003 the command latch (snd_cmd), $8005 the timer (0: read only in
the waits, which the schedule leaves out).  Any other access outside the ROM and the RAM $4000-$43FF stops the build (the
coverage's io).  LOOP ($0178) is the hook (snd_hook: the next tick or the end of the run).
"""
from pathlib import Path
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from sound import TOKEN, TICK_FX, FRAME_FX, LOOP, TICK, BOOT, ym_period, ym_noise, VTAB, rom
from paths import build_dir, require_coverage

ROM_END = 0x2000
# the natives (src/sound.s): the tick's start (the whole tick's shortcuts) and each channel's turn (`ld a,n; ld ($400C),a`)
CHANNELS = (0x0188, 0x01A3, 0x01BE, 0x01D9, 0x01F4, 0x020F)
NATIVES = {TICK: 'snd_tick', **{pc: 'snd_ch%d' % (i + 1) for i, pc in enumerate(CHANNELS)}}


def io_kind(a, rw):
    """an I/O address -> 'latch' 'timer' 'sn1' 'sn2' 'nop', 'bad', or None (ROM, RAM)"""
    if a < 0x2000 or 0x4000 <= a < 0x4400:
        return None
    if rw == 'r':
        return {0x8003: 'latch', 0x8005: 'timer'}.get(a, 'bad')
    return {0x8002: 'sn1', 0x8004: 'sn2', 0x8000: 'nop', 0x8001: 'nop', 0x8079: 'nop', 0xA003: 'nop'}.get(a, 'bad')


class SEmitter(z80x.Emitter):
    def x_ld(self, ins):
        dst, src = ins.ops
        if dst[0] == 'ind16' and io_kind(dst[1], 'w'):
            k = io_kind(dst[1], 'w')
            if src != ('r8', 'a') or k == 'bad':
                raise z80x.Unsupported('I/O store ' + ins.text)
            if k in ('sn1', 'sn2'):
                self.e('bsr snd_%s_w' % k)
            return                                # (nop: nothing)
        if src[0] == 'ind16' and io_kind(src[1], 'r'):
            k = io_kind(src[1], 'r')
            if dst != ('r8', 'a') or k == 'bad':
                raise z80x.Unsupported('I/O load ' + ins.text)
            self.e('move.b snd_cmd,d0' if k == 'latch' else 'moveq #0,d0')
            return
        z80x.Emitter.x_ld(self, ins)

    # the `add a,a ... jp (hl)` jump table (rst $18), emitted at its calls (Pooyan's sndgen)
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


def coverage():
    require_coverage('mikie', ['cover_sound101.pkl'])
    pcs, jumps, io = set(), set(), set()
    for f in sorted(build_dir('mikie').glob('cover_sound*.pkl')):
        d = pickle.loads(f.read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        io |= d.get('io', set())
    return {p for p in pcs if p < ROM_END}, {j for j in jumps if j < ROM_END}, io


def check_io(code, io):
    """every I/O access the coverage saw is a static `ld (nn),a` / `ld a,(nn)`"""
    for pc, a, rw in sorted(io):
        k = io_kind(a, rw)
        if k is None:
            continue
        ins = code.get(pc)
        if ins is None or k == 'bad' or ins.mn != 'ld' or ('ind16', a) not in ins.ops or ('r8', 'a') not in ins.ops:
            raise RuntimeError('I/O access %s %04X by %04X %s' % (rw, a, pc, ins.text if ins else '?'))


def image():
    r = rom()
    return r + bytes(0x10000 - len(r))


def dispatch_table(code, em):
    labels = {p: 'X%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'snd_token_ret'
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


def translate():
    rom_img = image()
    pcs, jumps, io = coverage()
    roots = {BOOT, 0x38, LOOP, TICK} | jumps
    cache = {}
    while True:
        code, tables = discover.discover(rom_img, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom_img, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    check_io(code, io)
    SEmitter.helper = {}
    cfg = z80x.Config(prefix='X', table='snd_dispatch', token_sym='snd_token_ret', mode='signed', block=0x10000,
                      iyaddr=0x5FF0, fshadow=0x5FF2, io_read_redirect={}, write_hooks=[], nmi_token=TOKEN,
                      table_entries=0x10000, rst28_tables=False, hl_tables=True, bit_s=False, inline_leaves=6,
                      inline_limit=ROM_END, inline_rst=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    kw = dict(emitter=SEmitter, ijmp_flags=True, flags_at={LOOP}, natives=NATIVES)   # (src/sound.s)
    em = compile_code(code, joins, cfg, {LOOP}, **kw)
    SEmitter.helper = helpers(code, em.live_in, jumps)
    em = compile_code(code, joins, cfg, {LOOP}, **kw)
    out = ['; generated: Mikie sound Z80 -> 68000 (games/mikie/tools/sndgen.py)', '\tsection text,code']
    out += [l.replace('z80_hook', 'snd_hook').replace('z80_badpc', 'snd_badpc').replace('z80_rnd', 'snd_badpc')
            .replace('z80_unsupported', 'snd_badpc') for l in em.lines]
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['X%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp snd_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em) + jump_tables(rom_img, em)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed sound instructions cannot be translated: %s' % seen)
    report = {'instructions': len(code), 'coverage': len(pcs),
              'helpers': {'%04X' % k: v[0] for k, v in sorted(SEmitter.helper.items())},
              'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing]}
    return '\n'.join(out) + '\n', report


def stubs():
    """effect (0-127) -> the voice block's address IX for the effects whose per-tick handler (table $1EA5) is `ld ix,nn`
    then the counter step $085E (`call $0357; ret`, $0357: `ld a,(ix+0); cp $FF; ret z; call $0395`, $0395: `dec (ix+1);
    ret nz`): such a tick only counts (ix+1) down unless (ix+0) is $FF or the counter reaches 0; 0 for the others"""
    r = rom()
    assert r[0x085E:0x0862] == bytes([0xCD, 0x57, 0x03, 0xC9]) and r[0x0357:0x035D] == bytes([0xDD, 0x7E, 0, 0xFE, 0xFF, 0xC8])         and r[0x035D:0x0361] == bytes([0xCD, 0x95, 0x03, 0xAF]) and r[0x0395:0x0399] == bytes([0xDD, 0x35, 1, 0xC0])
    out = []
    for e in range(128):
        t = r[0x1EA5 + 2 * e] | r[0x1EA5 + 2 * e + 1] << 8 if 0x1EA5 + 2 * e + 1 < len(r) else 0
        ok = t < 0x2000 and r[t] == 0xDD and r[t + 1] == 0x21 and (t + 4 == 0x085E or r[t + 4:t + 6] == bytes([0x18, (0x085E - t - 6) & 255]))
        out.append(r[t + 2] | r[t + 3] << 8 if ok else 0)
    return out


def data():
    """snd_data.s: the schedule's constants and the YM's tables"""
    out = ['; generated: Mikie sound data (games/mikie/tools/sndgen.py)',
           'SND_FRAME_FX = %d\t\t; an arcade frame (half Z80 cycles)' % FRAME_FX,
           'SND_TICK_FX = %d\t\t; a tick: 4096 cycles' % TICK_FX,
           'SND_LOOP_SW = $%04X\t\t; the loop\'s head $%04X, byte swapped' % (((LOOP & 255) << 8) | (LOOP >> 8), LOOP),
           'snd_loop_label = X%04X' % LOOP, 'snd_tick_label = X%04X' % TICK, 'snd_boot_label = X%04X' % BOOT,
           '\tsection data,data', '\teven']
    for chip in (0, 1):
        out.append('snd_ptab%d:	; SN%d tone period -> YM period' % (chip + 1, chip + 1))
        vals = [ym_period(n, chip) for n in range(1024)]
        for i in range(0, 1024, 16):
            out.append('	dc.w ' + ','.join('%d' % v for v in vals[i:i + 16]))
        out.append('snd_ntab%d:	; (2048 bytes on) SN%d: noise mode 3 by tone 2 period (< 32); +32: modes 0-2 (+3 unused)'
                   % (chip + 1, chip + 1))
        out.append('	dc.b ' + ','.join('%d' % ym_noise(3, n, chip) for n in range(32)))
        out.append('	dc.b ' + ','.join('%d' % ym_noise(m, 0, chip) for m in range(4)))
    st = stubs()
    blocks = sorted({v for v in st if v})
    out.append('snd_stub:\t; effect -> its voice block (the counter step), 0: none')
    for i in range(0, 128, 8):
        out.append('\tdc.w ' + ','.join('$%04X' % v for v in st[i:i + 8]))
    out.append('snd_stubg:\t; effect -> its voice block\'s number (0-%d), 0: none' % (len(blocks) - 1))
    for i in range(0, 128, 16):
        out.append('\tdc.b ' + ','.join('%d' % (blocks.index(v) if v else 0) for v in st[i:i + 16]))
    out.append('snd_vtab:\tdc.b ' + ','.join(map(str, VTAB)))
    out.append('\teven')
    return '\n'.join(out) + '\n'


def build():
    text, report = translate()
    bd = build_dir('mikie')
    (bd / 'snd_code.s').write_text(text)
    (bd / 'snd.rom').write_bytes(image()[:0x4000])
    (bd / 'snd_data.s').write_text(data())
    return report


if __name__ == '__main__':
    rep = build()
    print({k: v for k, v in rep.items() if k != 'unsupported'}, len(rep['unsupported']), 'unsupported')
