"""Pac-Man: the Z80 program (16 KB, flat) translated to 68000 code.

    python gen.py   ->  build/pacman/code_main.s (+ translation.json)

Roots: reset, the IM 2 targets ($3000 at boot, $008D the frame handler), the idle hook $238D and the coverage
(build/pacman/cover<seed>.pkl, ref/cover.py in the port's schedule).  The restarts that take data after them
(discover's rst_data): `rst $20` jumps through the word table behind it, `rst $28` posts a task (2 inline bytes) and
`rst $30` a timed task (3 inline bytes); both return past their data, so the code goes on there (a join: the ret
dispatches to it).
The runtime (src/pacman.s, machine.PacmanPort): z80_hook at $238D (d7 = the pc) returns to go on, or, with the task
ring empty, waits for the next arcade frame and delivers the IRQ: the hook's pc pushed, the vector's target entered.
`halt` (only $234A, the boot) jumps to pm_halt with the next pc in d7, which does the same.  `out ($00),a` stores the
IM 2 vector (pm_vector), `ei` / `di` the IRQ gate (pm_iff), `ld i,a` the I register (IADDR).
Memory-mapped I/O: the static reads of IN0 $5000, IN1 $5040, DSW1 $5080 and DSW2 $50C0 read IO_IN's bytes (the
runtime keeps the inputs there); stores to $5000-$50FF are plain stores (the runtime reads the latch byte $5000 for
the IRQ enable, the WSG registers $5040-$505F and the sprite coordinates $5060-$506F).  The stores to the video and
colour RAM ($4000-$47FF, the coverage's write sites) list the cell they hit (cell_dirty, cell_list) through pm_mark_*
routines that keep the flags.
"""
from pathlib import Path
import json
import os
import pickle
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from paths import build_dir, require_coverage
from machine import PacmanPort, load, skip_tests

BUILD = build_dir('pacman')
HOOKS = [PacmanPort.IDLE]
SEEDS = [int(x) for x in os.environ.get('PM_SEEDS', '').split(',') if x] or range(1, 13)
ROM_END = 0x4000
IRQ_TARGETS = (0x3000, 0x008D)              # the words at $3FFA and $3FFC
RST_DATA = {0x20: 'table', 0x28: 2, 0x30: 3}
IO_IN = {0x5000: 0x5100, 0x5040: 0x5101, 0x5080: 0x5102, 0x50C0: 0x5103}
IADDR = 0x5104
# the text printer ($2C5E) takes positions with bit 15 set from its string table for the top and bottom rows: A15 is
# not decoded, so they are video RAM; after `add ix,de` ($2C69) IX loses bit 15 (the colour address it pushes and the
# code address derived from it: the stores at $2C89 / $2C9B / $2CA4 / $2CB1)
IX_A15 = 0x2C69
HOLE = (0x4800, 0x4C00)                     # reads $BF (the runtime fills the block's bytes), never written
# calls of leaf functions of up to this many instructions are emitted in place, rst helpers and inner jumps too
INLINE = int(os.environ.get('PM_INLINE', '16'))


def image():
    """the program as the port runs it: the boot's tests patched out (machine.skip_tests)"""
    rom = skip_tests(b''.join(load(n) for n in ('pacman.6e', 'pacman.6f', 'pacman.6h', 'pacman.6j')))
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('pacman', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io, outs, halts = set(), set(), set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
        outs |= d['outs']
        halts |= d['halts']
    return pcs, jumps, writes, io, outs, halts


class PEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        if ins.ops != [('port', 0), ('r8', 'a')]:
            raise z80x.Unsupported('out ' + ins.text)
        self.e('move.b d0,pm_vector')

    def x_halt(self, ins):
        self.e('move.w #$%04X,d7' % (ins.pc + ins.length))
        self.e('jmp pm_halt')

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        super().emit_ins(pc, live_out_override, with_label)
        if pc == IX_A15:
            self.e('move sr,-(a7)')
            self.e('and.w #$7FFF,d4')         # (IX: d4)
            self.e('move (a7)+,ccr')
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def unmirror(a):
    """the address the board decodes: A15 not connected, A13 ignored from $4000 on"""
    a &= 0x7FFF
    return a & ~0x2000 if a >= 0x4000 else a


def tile_marks(code, writes):
    """pc -> the line that marks the video / colour RAM cell its store hit (a routine per address register; static
    stores mark their cell directly; block moves mark every cell)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0x4000 <= unmirror(a) < 0x4800}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr pm_mark_all'
            continue
        if ins.mn == 'rst' and ins.ops[0][1] == 0x08:
            out[pc] = 'bsr pm_mark_all'       # (the fill: ld (hl),a / inc hl / djnz)
            continue
        dst = (ins.ops[-1] if ins.mn in ('set', 'res') else ins.ops[0]) if ins.ops else None
        if ins.mn in ('push', 'call') or dst is None:
            raise RuntimeError('video RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'pea %d.w\n\tbsr pm_mark_n\n\taddq.l #4,a7' % (dst[1] & 0x3ff)
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tpea %d.w\n\tbsr pm_mark_n\n\taddq.l #4,a7' % ((dst[1] + 1) & 0x3ff)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd',
                'add', 'adc', 'sub', 'sbc', 'and', 'xor', 'or'):
            if ins.mn in ('add', 'adc', 'sub', 'sbc', 'and', 'xor', 'or'):
                raise RuntimeError('video RAM write by %04X %s (an ALU read?)' % (pc, ins.text))
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr pm_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr pm_mark_%s' % dst[1]
        else:
            raise RuntimeError('video RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def check_io(code, io, outs, halts):
    """the accesses the translation handles: static reads of the input ports, no access outside ROM and RAM but the
    I/O stores, `out ($00),a` alone, the one halt"""
    for pc, a, rw in sorted(io):
        ins = code.get(pc)
        if ins is None:
            continue
        if rw == 'r':
            if HOLE[0] <= a < HOLE[1]:
                continue
            if not (ins.mn == 'ld' and ins.ops[1] == ('ind16', a) and a in IO_IN):
                raise RuntimeError('I/O read of %04X by %04X %s' % (a, pc, ins.text))
        elif pc == PacmanPort.HALT or pc in (0x2C89, 0x2C9B, 0x2CA4, 0x2CB1) and 0x4000 <= unmirror(a) < 0x4800:
            continue                          # (the boot halt's push below SP $FFFF: pm_halt; the text printer: IX_A15)
        elif not 0x5000 <= a < 0x5100:
            raise RuntimeError('store to %04X by %04X %s' % (a, pc, ins.text))
    for pc, port, v in sorted(outs):
        if port != 0:
            raise RuntimeError('out to port %02X by %04X' % (port, pc))
    if halts - {PacmanPort.HALT}:
        raise RuntimeError('halts at %s' % sorted(halts))


def generate():
    rom = image()
    pcs, jumps, writes, io, outs, halts = coverage()
    pcs = {p for p in pcs if p < ROM_END}
    known = set(pcs)
    roots = {0, 0x38} | set(IRQ_TARGETS) | set(HOOKS) | {j for j in jumps if j < ROM_END}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | known), known=known, rst28_tables=False, hl_tables=True,
                                         rst_data=RST_DATA)
        code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
        missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
        if not missing:
            break
        roots |= missing
    check_io(code, io, outs, halts)
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=0x5106, fshadow=0x5108,
                      io_read_redirect=IO_IN, write_hooks=[], nmi_token=None, token_sym='z80_badpc',
                      rst28_tables=False, hl_tables=True, bit_s=False, iff_sym='pm_iff', iaddr=IADDR,
                      inline_leaves=INLINE, inline_limit=ROM_END, inline_rst=True, inline_jumps=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    for pc, ins in code.items():                # the continuations past the data of rst $28 / $30
        if ins.flow == 'rst' and isinstance(RST_DATA.get(ins.target), int):
            joins.add(pc + ins.length + RST_DATA[ins.target])
    marks = tile_marks(code, writes)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=PEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks)
    seen = [u for u in em.unsupported if u[0] in known]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Pac-Man Z80 -> 68000 (games/pacman/tools/gen.py)', '\tsection text,code']
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['Z%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp z80_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()},
              'tile_sites': len(marks), 'jumps': len(jumps), 'coverage': len(pcs),
              'discovered_only': len(set(code) - pcs), 'io': sorted(io)}
    return '\n'.join(out) + '\n', report, code


def dispatch_table(code, em):
    """a long per Z80 address in byte-swapped order (the word a ret reads from the Z80 stack): the translated label,
    else z80_badpc (Time Pilot's layout)"""
    labels = {p: 'Z%04X' % p for p in code if p not in em.no_entry}
    rows, run = ['\tcnop 0,4', 'z80_dispatch_sw:'], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append('\tdcb.l %d,z80_badpc' % run)
            run = 0
        rows.append('\tdc.l %s' % label)
    if run:
        rows.append('\tdcb.l %d,z80_badpc' % run)
    return rows


if __name__ == '__main__':
    text, report, _ = generate()
    (BUILD / 'code_main.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print({k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')}, len(report['unsupported']),
          'unsupported')
