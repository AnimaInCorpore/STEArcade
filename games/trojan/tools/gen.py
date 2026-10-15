"""Trojan main Z80 -> 68000: the whole program, bank-aware (after games/blktiger/tools/gen.py).

The program: $0000-$7FFF fixed, $8000-$BFFF a window on four 16 KB banks (tbu_06.13n: banks 0, 1; tbu_05.12n: 2, 3)
selected by bits 1-2 of $F80E.  Banked code is translated at virtual addresses VBASE + bank * $4000 + (pc - $8000)
(labels Z1xxxx); a jump from fixed code into the window goes through the dispatch of the bank selected then (BKxxxx
stubs), a call pushes the real address.  Data reads of the window go through aW = g_winbase (the bank's copy + $8000):
static ones always, indirect ones at the sites the coverage saw reading it (docs/coverage.json; TR_GUARD_ALL=1: every
indirect read).  The registers $F808 (sprite DMA), $F80C / $F80D (sound latches), $F80E (bank, NMI mask, flip) call
the runtime after `ld (nn),a`; a bank switch from banked code continues through the dispatch (the next instruction
is in the new bank).  The video RAM and palette writers (the coverage's store sites) set fg_written / bg_written /
pal_written for the renderer.
"""
from pathlib import Path
import json
import os
import pickle
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import z80dis
import discover
from z80x import Emitter, Unsupported
from translate import compile_code
from machine import load
from paths import build_dir

WIN_LO, WIN_HI, VBASE = 0x8000, 0xC000, 0x10000
IDLE = 0x0491
BUILD = build_dir('trojan')
DOCS = Path(__file__).resolve().parents[1] / 'docs'
REG_HOOKS = [(0xF808, 0xF808, 'tr_dma', None), (0xF80C, 0xF80C, 'tr_sound', None),
             (0xF80D, 0xF80D, 'tr_adpcm', None), (0xF80E, 0xF80E, 'tr_bank', None)]
FLAG_OF = {'fg': 'fg_written', 'bg': 'bg_written', 'pal': 'pal_written'}


def virt(pc, bank):
    return VBASE + bank * 0x4000 + pc - WIN_LO


def real(pc):
    return WIN_LO + ((pc - VBASE) & 0x3FFF) if pc >= VBASE else pc


def vsite(bank, pc):
    return virt(pc, bank) if bank >= 0 else pc


def image():
    banks = load('tb06.bin') + load('tb05.bin')
    return load('tb04.bin') + bytes([0x76]) * 0x8000 + banks


def decode(rom, pc):
    ins = z80dis.decode(rom, pc)
    if pc < VBASE:
        return ins
    bank = (pc - VBASE) // 0x4000

    def fix(o):
        if o[0] != 'addr':
            return o
        if ins.mn in ('jr', 'djnz'):
            # relative targets wrap at the Z80's 64 KB, not at the virtual bank
            delta = ((o[1] - ((pc + ins.length) & 0xFFFF) + 0x8000) & 0xFFFF) - 0x8000
            target = (real(pc) + ins.length + delta) & 0xFFFF
        else:
            target = o[1]
        return ('addr', virt(target, bank) if WIN_LO <= target < WIN_HI else target)
    ops = [fix(o) for o in ins.ops]
    target = next((o[1] for o in ops if o[0] == 'addr'), ins.target)
    return ins._replace(ops=ops, target=target)


def inside(pc):
    return pc < WIN_LO or pc >= VBASE


def find_code(rom, roots, known, tables):
    """recursive descent (banked decode); `rst $30` pops its return address and jumps through the word table behind
    it (indexed by A): its entries are code (tables: the set of their targets, entered by a computed jump)"""
    code = {}
    work = list(roots)
    while work:
        pc = work.pop()
        while inside(pc) and pc < len(rom) and pc not in code:
            i = decode(rom, pc)
            code[pc] = i
            nxt = pc + i.length
            if i.flow in ('jmp', 'jcc', 'call', 'ccall', 'rst') and i.target is not None:
                work.append(i.target)
            if i.flow == 'rst' and i.target == 0x30:
                bank = (pc - VBASE) // 0x4000 if pc >= VBASE else -1
                a, end = nxt, (VBASE + (bank + 1) * 0x4000) if bank >= 0 else WIN_LO
                while a + 1 < end and a not in known:
                    t = rom[a] | rom[a + 1] << 8
                    if WIN_LO <= t < WIN_HI:
                        if bank < 0:
                            break
                        t = virt(t, bank)
                    elif not 0x100 <= t < WIN_LO:
                        break
                    work.append(t)
                    tables.add(t)
                    if t >= nxt:
                        end = min(end, t)
                    a += 2
                break
            if i.flow in ('jmp', 'ret', 'ijmp'):
                break
            pc = nxt
    return code


def coverage():
    """the coverage's facts: from build/trojan/cover*.pkl when there are any (and docs/coverage.json written again),
    else from docs/coverage.json"""
    doc = DOCS / 'coverage.json'
    covers = sorted(BUILD.glob('cover*.pkl'))
    if covers:
        pcs, wread, stores = set(), set(), {}
        for p in covers:
            d = pickle.loads(p.read_bytes())
            pcs |= {vsite(b, pc) for b, pc in d['pcs']}
            wread |= {vsite(b, pc) for b, pc in d['wread']}
            for (b, pc), regions in d['stores'].items():
                stores.setdefault(vsite(b, pc), set()).update(regions)
        doc.write_text(json.dumps({'pcs': sorted(pcs), 'window_reads': sorted(wread),
                                   'stores': {str(k): sorted(v) for k, v in sorted(stores.items())}}) + '\n')
        return pcs, wread, stores
    d = json.loads(doc.read_text())
    return set(d['pcs']), set(d['window_reads']), {int(k): set(v) for k, v in d['stores'].items()}


class TrEmitter(Emitter):
    def __init__(self, *a, window_sites=(), dirty=None, **k):
        super().__init__(*a, **k)
        self.window_sites = set(window_sites)
        self.dirty = dirty or {}
        self.stubs = set()

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:             # a window address from fixed code: the bank decides
            self.stubs.add(pc)
            return 'BK%04X' % pc
        return Emitter.label_of(self, pc)

    def ret_value(self, pc):                  # (a call pushes the real address)
        return real(pc)

    def direct_ok(self, rp):                  # (a return point in the window: checked against the bank, dispatch_ret)
        return rp in self.code

    def dispatch_ret(self, pc=None):
        """z80x's direct returns, a return point in the window only when its bank is the one selected"""
        self.e('moveq #0,d7')
        self.e('move.w (a5)+,d7')
        for rp in self.ret_cands().get(pc, ()):
            self.e('cmp.w #$%04X,d7' % z80x.swap16(self.ret_value(rp)))
            if rp >= VBASE:
                skip = self.new_label()
                self.e('bne.s %s' % skip)
                self.e('cmp.b #%d,g_bank' % ((rp - VBASE) // 0x4000 * 4))
                self.e('beq %s' % self.label_of(rp))
                self.lines.append(skip + ':')
            else:
                self.e('beq %s' % self.label_of(rp))
        self.dispatch_d7()

    def mem(self, addr, off=0, io_read=False):
        if addr >= 0x10000:
            return 'g_iy' if addr == 0x10000 and off == 0 else 'g_fshadow'
        a = (addr + off) & 0xFFFF
        if WIN_LO <= a < WIN_HI:
            return '%d(aW)' % (a - 0x10000)
        return Emitter.mem(self, addr, off, io_read)

    win_src = None

    def ind(self, reg, disp=0):
        if self.win_src == reg:              # a block instruction reading the window
            return '%d(aW,%s.w)' % (disp, reg) if disp else '(aW,%s.w)' % reg
        return Emitter.ind(self, reg, disp)

    def win_check(self, reg, disp=0):
        """aW = the base for the Z80 address reg + disp: the window's ($8000-$BFFF: signed words below -$4000) or a6"""
        l = self.new_label()
        return ['lea (a6),aW', 'cmp.w #$%04X,%s' % ((0xC000 - disp) & 0xFFFF, reg), 'bge.s %s' % l,
                'move.l g_winbase,aW', l + ':']

    def block_win(self, fn, ins):
        if ins.pc in self.window_sites:
            for line in self.win_check('d3'):
                self.lines.append(line) if line.endswith(':') else self.e(line)
            self.win_src = 'd3'
        try:
            fn(ins)
        finally:
            self.win_src = None

    def x_ldir(self, ins): self.block_win(super().x_ldir, ins)
    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    storing = False

    def write8(self, op, src_ea):             # (z80x's write8 takes its address from read8: a store is not guarded)
        self.storing = True
        try:
            return Emitter.write8(self, op, src_ea)
        finally:
            self.storing = False

    def read8(self, op, io_read=True):
        pre, ea = Emitter.read8(self, op, io_read)
        if op[0] == 'ind' and not self.storing and self.cur is not None and self.cur.pc in self.window_sites:
            match = re.fullmatch(r'(-?\d+)?\(a6,(d\d|a2)\.w\)', ea)
            if not match:
                raise Unsupported('indirect access %s' % ea)
            reg = match[2]
            if reg == 'a2':                 # (IY with z80x.FAST: the low word of a2, whose upper word is not 0)
                pre += ['move.w a2,d5']
                reg = 'd5'
            pre += self.win_check(reg, int(match[1] or 0))
            ea = '%s(aW,%s.w)' % (match[1] or '', reg)
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        Emitter.emit_ins(self, pc, live_out_override, with_label)
        self.window_wrap(n0)                  # (z80x: a0 = the window, loaded at the instruction's start)
        ins = self.code[pc]
        if pc in self.dirty:
            for flag in self.dirty[pc]:
                self.e('st %s' % flag)        # (Scc leaves the flags alone)
        if pc >= VBASE and ins.mn == 'ld' and ins.ops[0] == ('ind16', 0xF80E):
            # a bank switch from banked code: the next instruction is the new bank's
            self.e('move.w #$%04x,d7' % real(pc + ins.length))
            self.e('jmp tr_dispatch')

    def dispatch_d7(self):
        self.e('ror.w #8,d7')
        self.e('jmp tr_dispatch')

    def _incdec(self, ins, op):
        """inc / dec a whose H is read (a daa after it: the timer at $05D8): H from the low nibble (Commando's gen)"""
        if self.lo & z80x.H and ins.ops[0] == ('r8', 'a'):
            self.e('move.w d0,-(sp)')
            old = self.lo
            self.lo &= ~z80x.H
            Emitter._incdec(self, ins, op)
            self.lo = old
            self.e('move.w (sp)+,d7')
            self.e('and.w #15,d7')
            self.e('bclr #5,d6')
            label = self.new_label()
            self.e('cmp.w #%d,d7' % (15 if op == 'addq' else 0))
            self.e('bne.s ' + label)
            self.e('bset #5,d6')
            self.lines.append(label + ':')
        else:
            Emitter._incdec(self, ins, op)

    def x_in(self, ins):
        raise Unsupported('in')

    def x_out(self, ins):
        raise Unsupported('out')


def generate(extra_roots=()):
    rom = image()
    pcs, wread, stores = coverage()
    roots = {0, 0x66, IDLE, *extra_roots}
    saved = discover.decode
    discover.decode = decode
    skip_cache = {}
    tables = set()
    try:
        while True:
            code = find_code(rom, sorted(roots | pcs), pcs, tables)
            cont = discover.skip_returns(rom, code, inside, skip_cache)
            missing = cont - set(code)
            if not missing:
                break
            roots |= missing
    finally:
        discover.decode = saved
    # the registers: what the program stores there other than `ld (nn),a` would miss its hook
    for pc, regions in stores.items():
        if 'reg' in regions and pc in code:
            i = code[pc]
            if not (i.mn == 'ld' and i.ops[0][0] == 'ind16' and i.ops[1] == ('r8', 'a')):
                raise RuntimeError('register store %s at %x is not ld (nn),a' % (i.text, pc))
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0xC000, iyaddr=0x10000, fshadow=0x10002,
                      io_read_redirect={}, write_hooks=REG_HOOKS, rst28_tables=False, bit_s=True, **z80x.FAST)
    indirect = {pc for pc, ins in code.items() if any(o[0] == 'ind' for o in ins.ops)
                or ins.mn in ('ldir', 'lddr', 'ldi', 'ldd', 'cpi', 'cpir')}
    sites = indirect if os.environ.get('TR_GUARD_ALL') else indirect & wread
    dirty = {pc: sorted(FLAG_OF[r] for r in regions if r in FLAG_OF) for pc, regions in stores.items()}
    dirty = {pc: f for pc, f in dirty.items() if f}
    joins = set(roots) | tables
    em = compile_code(code, joins, cfg, {IDLE}, emitter=TrEmitter, ijmp_flags=True, flags_at={IDLE},
                      window_sites=sites, dirty=dirty)
    banks = sorted({(pc - VBASE) // 0x4000 for pc in code if pc >= VBASE})
    report = {'instructions': len(code), 'unsupported': [u for u in em.unsupported if u[0] in pcs],
              'unsupported_uncovered': len([u for u in em.unsupported if u[0] not in pcs]), 'window_sites': len(sites),
              'indirect': len(indirect), 'banks': banks, 'dirty_sites': len(dirty), 'covered': len(pcs)}
    # The dispatch tables (tr_dispatch), as data: a word per Z80 address, (the entry - the region's base) / 2.
    # Regions: the fixed code below $4000, from $4000, each bank's code (gen.py of Black Tiger).
    entries = sorted(pc for pc in code if pc not in em.no_entry)
    regions = [('lo', [pc for pc in entries if pc < 0x4000]), ('hi', [pc for pc in entries if 0x4000 <= pc < WIN_LO])]
    regions += [('b%d' % b, [pc for pc in entries if VBASE + b * 0x4000 <= pc < VBASE + (b + 1) * 0x4000])
                for b in banks]
    lines = list(em.lines)
    where = {}
    for i, line in enumerate(lines):
        mm = re.match(r'Z([0-9A-F]+):', line)
        if mm:
            where[int(mm.group(1), 16)] = i
    starts = [min(where[pc] for pc in r) for _, r in regions]
    inserts = []
    for n, (name, r) in enumerate(regions):
        first, end = starts[n], starts[n + 1] if n + 1 < len(regions) else len(lines)
        if not all(first <= where[pc] < end for pc in r):
            raise RuntimeError('dispatch region %s: the code is not in address order' % name)
        stub = next(i for i in range((first + end) // 2, end)
                    if re.match(r'\t(bra|jmp|rts)\b', lines[i]) and not lines[i].startswith('\tjmp (a0,'))
        inserts += [(first, 'tr_base_%s:' % name), (stub + 1, 'tr_bad_%s:\n\tjmp z80_badpc' % name)]
    for i, text in sorted(inserts, reverse=True):
        lines.insert(i, text)
    out = ['; Generated: Trojan main Z80, the fixed ROM and the four banks', '\tsection text,code', *lines]
    for pc in sorted(em.refs - set(code)):
        out += ['Z%04X:' % pc, '\tmove.w #$%04x,d7' % real(pc), '\tjmp z80_badpc']
    for pc in sorted(em.stubs):
        out += ['BK%04X:' % pc, '\tmove.w #$%04x,d7' % pc, '\tjmp tr_dispatch']

    def table(name, r, index):
        rows, run, bad = [], 0, '(tr_bad_%s-tr_base_%s)/2' % (name, name)
        at = {index(pc): pc for pc in r}
        for i in range(0x4000):
            if i not in at:
                run += 1
                continue
            if run:
                rows.append('\tdcb.w %d,%s' % (run, bad))
                run = 0
            rows.append('\tdc.w (Z%04X-tr_base_%s)/2' % (at[i], name))
        if run:
            rows.append('\tdcb.w %d,%s' % (run, bad))
        return rows
    out += ['\tsection data,data', '\teven', 'tr_fixed_dispatch:']
    out += table('lo', regions[0][1], lambda pc: pc) + table('hi', regions[1][1], lambda pc: pc - 0x4000)
    for (name, r), b in zip(regions[2:], banks):
        out += ['\tdc.l tr_base_%s' % name, 'tr_window_dispatch%d:' % b] + table(name, r, lambda pc: real(pc) - WIN_LO)
    out += ['tr_dispatch_targets:                ; (0: a bank without code)',
            '\tdc.l ' + ','.join('tr_window_dispatch%d' % b if b in banks else '0' for b in range(4))]
    out += ['\tsection text,code']
    return '\n'.join(out) + '\n', report, code


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_trojan.s').write_text(text)
    print(report)
