"""Pooyan: the sound board's Z80 driver (8 KB, Time Pilot's board) translated to 68000 code (engine/z80x.py).

    from sndgen import generate; text, report = generate()   -> build/pooyan/snd_code.s

Labels X<pc>, the dispatch table snd_dispatch_sw, the register map of the main program's translation (z80x.FAST: d0
A, d1 BC (byte-swapped), d2 DE, d3 HL, d4 IX, a2 IY, d6 the flags, a5 SP, a6 the sound CPU's 64 KB block, a4 the
table); src/sound.s saves the main program's registers around it.

The board's AYs are memory-mapped (tools/sound.py): the static loads and stores of $4000-$7FFF become the AY accesses
(SEmitter.x_ld): `ld (nn),a` with bit 12 of nn set selects the register (snd_addr + chip: A & 15), without it writes the
data into the register file snd_ay (marking snd_dirty, and snd_env + chip for the envelope's shape); `ld a,(nn)` reads a
register through snd_in (port A of AY #1: the command latch, its port B: the timer, 0 here; the AY-3-8910's read masks).
Any other access to $4000-$7FFF stops the build (the coverage's io: only static ones).  The filter stores ($8000-$FFFF)
stay plain stores into the block (the STE has no filters).  Nothing here is Pooyan's but the ROM and the entry points:
Time Pilot's driver on the same board can take the same emitter.

The runtime enters at $0000 (the boot), $0038 (a command, TOKEN as the return address) and TICK (a tick, after the
timer waits) and comes back at the loop's head LOOP (the hook snd_hook) or TOKEN.
"""
from pathlib import Path
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from sound import LOOP, TICK, TOKEN, rom
from paths import build_dir, require_coverage

ROM_END = 0x3000                          # (the board's ROM space; Pooyan fills $0000-$1FFF)
GAME = 'pooyan'


def image():
    r = rom()
    return r + bytes(0x10000 - len(r))


def ay_port(a):
    """$4000-$7FFF -> (chip, is_address) (MAME timeplt_sound_map: data $4000 / $6000, address $5000 / $7000, mirrors
    over $0FFF), else None"""
    if 0x4000 <= a < 0x8000:
        return (a >> 13) & 1, bool(a & 0x1000)
    return None


class SEmitter(z80x.Emitter):
    def x_ld(self, ins):
        dst, src = ins.ops
        if dst[0] == 'ind16' and ay_port(dst[1]):
            k, is_addr = ay_port(dst[1])
            if src != ('r8', 'a'):
                raise z80x.Unsupported('AY store ' + ins.text)
            if is_addr:
                self.e('moveq #15,d7')
                self.e('and.b d0,d7')
                self.e('move.b d7,snd_addr+%d' % k)
                return
            skip = self.new_label()
            self.e('moveq #0,d7')
            self.e('move.b snd_addr+%d,d7' % k)
            self.e('lea snd_ay+%d,a0' % (16 * k))
            self.e('move.b d0,(a0,d7.w)')
            self.e('st snd_dirty')
            self.e('cmp.b #13,d7')
            self.e('bne.s %s' % skip)
            self.e('st snd_env+%d' % k)
            self.lines.append(skip + ':')
            return
        if src[0] == 'ind16' and ay_port(src[1]):
            k, is_addr = ay_port(src[1])
            if dst != ('r8', 'a') or is_addr:
                raise z80x.Unsupported('AY load ' + ins.text)
            self.e('moveq #%d,d7' % k)
            self.e('bsr snd_in')
            self.e('move.b d7,d0')            # (ld a,(nn): no flags)
            return
        for op in (dst, src):
            if op[0] == 'ind16' and ay_port(op[1]) is None and 0x4000 <= op[1] < 0x8000:
                raise z80x.Unsupported('AY access ' + ins.text)
        z80x.Emitter.x_ld(self, ins)

    # ---- the driver's helpers, emitted at their calls (helpers(): recognised by their code) -----------------------
    helper = {}                               # pc -> ('select', chip, ret pc) | ('write', chip, ret pc) | ('table', ret pc)

    def ay_select_read(self, k):
        """`ld (addr k),a; ld a,(data k)`: A & 15 selects the register, A = its value (snd_in's reads, inline)"""
        self.e('moveq #15,d7')
        self.e('and.b d0,d7')
        self.e('move.b d7,snd_addr+%d' % k)
        if k == 0:
            n1, n2 = self.new_label(), self.new_label()
            self.e('cmp.b #14,d7')
            self.e('bne.s %s' % n1)
            self.e('move.b snd_latch,snd_ay+14')
            self.e('bra.s %s' % n2)
            self.lines.append(n1 + ':')
            self.e('cmp.b #15,d7')
            self.e('bne.s %s' % n2)
            self.e('clr.b snd_ay+15')
            self.lines.append(n2 + ':')
        self.e('lea snd_ay+%d,a0' % (16 * k))
        self.e('move.b (a0,d7.w),d0')
        self.e('lea snd_mask,a0')
        self.e('and.b (a0,d7.w),d0')

    def ay_write_bc(self, k):
        """`ld a,b; (select-read k); ld a,c; ld (data k),a`: register B & 15 := C, A = C.  (The read in between goes
        to A, which C replaces: it only matters for the ports, registers 14 / 15, and the write replaces it there.)"""
        self.e('moveq #0,d7')
        pre, eb = self.read8(('r8', 'b'))
        for l in pre:
            self.e(l)
        self.e('move.b %s,d7' % eb)
        self.e('and.b #15,d7')
        self.e('move.b d7,snd_addr+%d' % k)
        pre, ec = self.read8(('r8', 'c'))
        for l in pre:
            self.e(l)
        self.e('move.b %s,d0' % ec)
        skip = self.new_label()
        self.e('lea snd_ay+%d,a0' % (16 * k))
        self.e('move.b d0,(a0,d7.w)')
        self.e('st snd_dirty')
        self.e('cmp.b #13,d7')
        self.e('bne.s %s' % skip)
        self.e('st snd_env+%d' % k)
        self.lines.append(skip + ':')

    def emit_helper(self, h, site=None):
        if h[0] == 'select':
            self.ay_select_read(h[1])
        elif h[0] == 'write':
            self.ay_write_bc(h[1])
        else:
            self.table_jump(h[2][site])

    def table_jump(self, base):
        """`add a,a; add a,l; ld l,a; ld a,h; adc a,0; ld h,a; ld a,(hl); inc hl; ld h,(hl); ld l,a; jp (hl)` called
        after `ld hl,base`: HL = the word at base + 2 (A & $7F), A = its low byte, S, Z and C clear (the `adc a,0` of a
        table below $7F00), a jump there; through snd_jt<base> (jump_tables: each entry the label and HL)"""
        self.e('moveq #$7F,d7')
        self.e('and.b d0,d7')
        self.e('lsl.w #3,d7')
        self.e('lea snd_jt%04X,a0' % base)
        self.e('move.w 4(a0,d7.w),d3')        # (HL; its upper word, HL', kept)
        self.e('move.b d3,d0')                # (A: the low byte)
        self.e('clr.b d6')                    # (S, Z, C clear)
        self.e('move.l (a0,d7.w),a0')
        self.e('jmp (a0)')

    def x_rst(self, ins):
        h = self.helper.get(ins.ops[0][1])
        if h is None:
            return z80x.Emitter.x_rst(self, ins)
        if h[0] == 'table':
            self.push_ret(ins.pc + ins.length)
        self.emit_helper(h, ins.pc)

    def x_call(self, ins):
        h = self.helper.get(ins.target) if ins.ops[0][0] == 'addr' else None
        if h is None:
            return z80x.Emitter.x_call(self, ins)
        if h[0] == 'table':
            self.push_ret(ins.pc + ins.length)
        self.emit_helper(h, ins.pc)

    def x_jp(self, ins):
        h = self.helper.get(ins.ops[0][1]) if ins.ops[0][0] == 'addr' else None
        if h is None:
            return z80x.Emitter.x_jp(self, ins)
        self.emit_helper(h, ins.pc)           # (a tail call: the helper's ret returns to the caller's caller)
        if h[0] != 'table':
            self.dispatch_ret(h[-1])

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)


def helpers(code, live_in, jumps):
    """the helpers SEmitter emits at their calls, recognised by their instructions (Time Pilot's driver has its own
    at other addresses): pc -> ('select', chip, ret pc) for `ld (address k),a; ld a,(data k); ret`; ('write', chip,
    ret pc) for `ld a,b; rst/call <select k>; ld a,c; ld (data k),a; ret`; ('table', ret pc) for the jump table of
    `add a,a ... jp (hl)` when every call of it (rst, call or jp; none a jump target) follows `ld hl,nn` with nn in $0100-$7DFF (the table's high byte
    and its carry stay below $80: the `adc a,0` leaves S, Z and C clear) and no computed jump's target reads other
    flags than those (a target may read them: Pooyan's `rra` at $01E2 after `call $01DC` reads the carry)"""
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
    for pc in code:
        s = seq(pc, 3)
        if s and s[0].mn == 'ld' and s[0].ops[0][0] == 'ind16' and s[0].ops[1] == ('r8', 'a') \
                and (ay_port(s[0].ops[0][1]) or (0, False))[1] and s[1].mn == 'ld' and s[1].ops[0] == ('r8', 'a') \
                and s[1].ops[1][0] == 'ind16' and ay_port(s[1].ops[1][1]) == (ay_port(s[0].ops[0][1])[0], False) \
                and s[2].text == 'ret':
            out[pc] = ('select', ay_port(s[0].ops[0][1])[0], s[2].pc)
    for pc in code:
        s = seq(pc, 5)
        if s and s[0].text == 'ld a,b' and s[1].flow in ('rst', 'call') and s[1].mn in ('rst', 'call') \
                and len(s[1].ops) == 1 and s[1].target in out and s[2].text == 'ld a,c' and s[3].mn == 'ld' \
                and s[3].ops[1] == ('r8', 'a') and s[3].ops[0][0] == 'ind16' \
                and ay_port(s[3].ops[0][1]) == (out[s[1].target][1], False) and s[4].text == 'ret':
            out[pc] = ('write', out[s[1].target][1], s[4].pc)
    entered = {i.target for i in code.values()} | set(jumps)     # (a call entered past its `ld hl,nn`: HL unknown)
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
    """snd_jt<base> for the table helper's bases: 128 entries (A & $7F) of the target's label (snd_badpc if it is
    not translated) and the target as HL"""
    labels = {p: 'X%04X' % p for p in em.code if p not in em.no_entry}
    bases = sorted({b for h in SEmitter.helper.values() if h[0] == 'table' for b in h[2].values()})
    rows = ['\tcnop 0,4']
    for base in bases:
        rows.append('snd_jt%04X:' % base)
        for i in range(128):
            t = rom_img[base + 2 * i] | rom_img[base + 2 * i + 1] << 8
            rows.append('\tdc.l %s\n\tdc.w $%04X,0' % (labels.get(t, 'snd_badpc'), t))
    return rows


def coverage():
    """the pcs, computed jumps and I/O accesses of ref/cover_sound.py's runs"""
    require_coverage(GAME, ['cover_sound0.pkl'])
    pcs, jumps, io = set(), set(), set()
    for f in sorted(build_dir(GAME).glob('cover_sound*.pkl')):
        d = pickle.loads(f.read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        io |= d.get('io', set())
    return {p for p in pcs if p < ROM_END}, {j for j in jumps if j < ROM_END}, io


def check_io(code, io):
    """every AY access the coverage saw is a static `ld (nn),a` / `ld a,(nn)` (the emitter's forms)"""
    for pc, a, rw in sorted(io):
        if a >= 0x8000:
            continue
        ins = code.get(pc)
        if ins is None or ins.mn != 'ld' or ('ind16', a) not in ins.ops or ('r8', 'a') not in ins.ops:
            raise RuntimeError('AY access %s %04X by %04X %s' % (rw, a, pc, ins.text if ins else '?'))


def generate():
    rom_img = image()
    pcs, jumps, io = coverage()
    roots = {0, 0x38, LOOP, TICK} | jumps
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
                      iyaddr=0x2FF0, fshadow=0x2FF2, io_read_redirect={}, write_hooks=[], nmi_token=TOKEN,
                      table_entries=0x10000, rst28_tables=False, hl_tables=True, bit_s=False, inline_leaves=6,
                      inline_limit=ROM_END, inline_rst=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, {LOOP}, emitter=SEmitter, ijmp_flags=True, flags_at={LOOP})
    SEmitter.helper = helpers(code, em.live_in, jumps)        # (the liveness of a first pass: the same code)
    em = compile_code(code, joins, cfg, {LOOP}, emitter=SEmitter, ijmp_flags=True, flags_at={LOOP})
    out = ['; generated: Pooyan sound Z80 -> 68000 (games/pooyan/tools/sndgen.py)', '\tsection text,code']
    out += [l.replace('z80_hook', 'snd_hook').replace('z80_badpc', 'snd_badpc').replace('z80_rnd', 'snd_badpc')
            for l in em.lines]
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['X%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp snd_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em) + jump_tables(rom_img, em)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed sound instructions cannot be translated: %s' % seen)
    report = {'instructions': len(code), 'coverage': len(pcs),
              'helpers': {'%04X' % k: v[0] for k, v in sorted(SEmitter.helper.items())}, 'unsupported': em.unsupported,
              'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()}}
    return '\n'.join(out) + '\n', report


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


if __name__ == '__main__':
    text, rep = generate()
    (build_dir(GAME) / 'snd_code.s').write_text(text)
    print({k: v for k, v in rep.items() if k not in ('tables', 'unsupported')}, len(rep['unsupported']), 'unsupported')
