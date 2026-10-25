"""Gyruss: the main Z80 program (24 KB, flat) translated to 68000 code.

    python gen.py   ->  build/gyruss/code_main.s (+ translation.json)

Coverage: build/gyruss/cover<seed>.pkl (ref/cover.py, the port's schedule).  The runtime (src/gyruss.s) delivers the
NMI at the idle hook 05F7 (machine.GyrussPort: the foreground's task loop with an empty queue): the hook calls
z80_hook (d7 = pc), which returns to go on or delivers the NMI with TOKEN as its return address.
Memory-mapped I/O: the static reads of $C000-$C1FF read io_in + (address - $C000) / 32 (DSW2, SYSTEM, P1, P2, DSW1,
DSW3: the runtime keeps them); the stores there are plain stores into the block (the runtime reads the latch bytes
$C180 (NMI mask) and $C185 (flip) and the sound latch $C100 from it), and `ld ($C080),a` (the sound IRQ) calls
gy_sound.  The stores to the video RAM ($8000-$87FF, the coverage's write sites) mark the 32-byte row they hit in
cell_list (once each, cell_dirty: the colour and code bytes of a cell share it) through gy_mark_* routines that keep the
flags; the renderer compares only the marked rows with its copy.
`rst $30` is a jump through the word table behind it (0030: pop hl; rst $10; ex de,hl; jp (hl)): the table is data
(no fall-through: decode gives it the flow of a computed jump), its entries code (RST30_TABLES: the index's bound from
the code before the site; generate() checks that every computed jump the coverage saw lands in a known table).
"""
from pathlib import Path
import os
import sys
import pickle
import json
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import z80dis
import discover
from translate import compile_code
from paths import build_dir, require_coverage
from machine import GyrussPort, load

BUILD = build_dir('gyruss')
HOOKS = [GyrussPort.MAIN_IDLE]
TOKEN = GyrussPort.TOKEN
SEEDS = [int(x) for x in os.environ.get('GY_SEEDS', '').split(',') if x] or range(1, 13)   # (GY_SEEDS: other coverage files)
ROM_END = 0x6000
# rst $30 sites: entries (the bound of the index: `and n` before it, else the table up to the code or data after it)
RST30_TABLES = {0x0189: 4,     # and 3
                0x082F: 10,    # [$942C]
                0x08A4: 4,     # and 3
                0x0F01: 2,     # [$942C] (0 / 1 here: data follows)
                0x0F2B: 5,     # [$942C]
                0x1025: 8,     # [$942C]
                0x2540: 12,    # (ix+10)
                0x268A: 16,    # and $0F
                0x2832: 16,    # and $0F
                0x3180: 32,    # and $1F
                0x4648: 3,     # (ix+9)
                0x4B6F: 8}     # and 7
IO_IN = {0xC000: 0, 0xC080: 4, 0xC0A0: 5, 0xC0C0: 6, 0xC0E0: 7, 0xC100: 8}   # io_in + (a - $C000) / 32


def image():
    rom = b''.join(load(n) for n in ('gyrussk.1', 'gyrussk.2', 'gyrussk.3'))
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('gyruss', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io = set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
    return pcs, jumps, writes, io


def decode(rom, pc):
    """z80dis.decode with `rst $30` as a computed jump (no fall-through into its table)"""
    ins = z80dis.decode(rom, pc)
    if ins.mn == 'rst' and ins.target == 0x30:
        ins = ins._replace(flow='ijmp')
    return ins


def table_targets(rom):
    """site -> the entries of its rst $30 table"""
    return {s: [rom[s + 1 + 2 * k] | rom[s + 2 + 2 * k] << 8 for k in range(n)] for s, n in RST30_TABLES.items()}


class GEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if io_read and 0xC000 <= a < 0xC200:
            if a not in IO_IN:
                raise z80x.Unsupported('read of %04X' % a)
            return 'io_in+%d' % IO_IN[a]
        return z80x.Emitter.mem(self, addr, off, io_read)

    def x_in(self, ins):
        raise z80x.Unsupported('in ' + ins.text)

    def x_out(self, ins):
        raise z80x.Unsupported('out ' + ins.text)

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        super().emit_ins(pc, live_out_override, with_label)
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def tile_marks(code, writes):
    """pc -> the line that marks the video RAM row its store hit (a routine per address register; static stores mark
    their row directly; block moves mark every row)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0x8000 <= a < 0x8800}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr gy_mark_all'
            continue
        dst = (ins.ops[-1] if ins.mn in ('set', 'res') else ins.ops[0]) if ins.ops else None
        if ins.mn in ('push', 'call', 'rst') or dst is None:
            raise RuntimeError('video RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'pea %d.w\n\tbsr gy_mark_n\n\taddq.l #4,a7' % (dst[1] & 0x3ff)
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tpea %d.w\n\tbsr gy_mark_n\n\taddq.l #4,a7' % ((dst[1] + 1) & 0x3ff)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'):
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr gy_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr gy_mark_%s' % dst[1]
        else:
            raise RuntimeError('video RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def check_io(code, io):
    """the I/O accesses the translation handles: static reads of the input ports, `ld ($C080),a` for the sound IRQ"""
    for pc, a, rw in sorted(io):
        ins = code.get(pc)
        if ins is None:
            continue
        if rw == 'r':
            if not (ins.mn == 'ld' and ins.ops[1] == ('ind16', a)):
                raise RuntimeError('I/O read of %04X by %04X %s' % (a, pc, ins.text))
        elif a == 0xC080:
            if not (ins.mn == 'ld' and ins.ops == [('ind16', a), ('r8', 'a')]):
                raise RuntimeError('sound IRQ by %04X %s' % (pc, ins.text))


def generate():
    rom = image()
    pcs, jumps, writes, io = coverage()
    pcs = {p for p in pcs if p < ROM_END}
    tables30 = table_targets(rom)
    entries = {t for ts in tables30.values() for t in ts}
    roots = {0, 0x66} | set(HOOKS) | {j for j in jumps if j < ROM_END} | entries
    saved = discover.decode
    discover.decode = decode
    cache = {}
    try:
        while True:
            code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False)
            code = {pc: ins for pc, ins in code.items() if pc < ROM_END}
            missing = discover.skip_returns(rom, code, lambda pc: pc < ROM_END, cache) - set(code)
            if not missing:
                break
            roots |= missing
    finally:
        discover.decode = saved
    check_io(code, io)
    for s, ts in tables30.items():
        if s in code and code[s].mn != 'rst':
            raise RuntimeError('rst $30 table site %04X is not code' % s)
    rst30 = sorted(pc for pc, ins in code.items() if ins.mn == 'rst' and ins.target == 0x30 and pc in pcs)
    if set(rst30) - set(RST30_TABLES):
        raise RuntimeError('rst $30 sites without a table: %s' % ['%04X' % p for p in rst30 if p not in RST30_TABLES])
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=0x9FF0, fshadow=0x9FF2,
                      io_read_redirect={}, write_hooks=[(0xC080, 0xC080, 'gy_sound', None)], nmi_token=TOKEN,
                      token_sym='z80_irq_ret', rst28_tables=False, bit_s=True, **z80x.FAST)
    joins = set(roots)
    tables.update({s: (s + 1, ts) for s, ts in tables30.items()})
    for nxt, targets in tables.values():
        joins |= set(targets)
    marks = tile_marks(code, writes)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=GEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Gyruss main Z80 -> 68000 (games/gyruss/tools/gen.py)', '\tsection text,code']
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ['Z%04X:\tmove.w #$%04X,d7' % (p, p), '\tjmp z80_badpc']
    out += ['\tsection data,data'] + dispatch_table(code, em)
    report = {'instructions': len(code), 'unsupported': em.unsupported, 'missing': ['%04X' % p for p in missing],
              'tables': {'%04X' % k: ['%04X' % t for t in v[1]] for k, v in tables.items()},
              'tile_sites': len(marks), 'jumps': len(jumps), 'io': sorted(io)}
    return '\n'.join(out) + '\n', report, code


def dispatch_table(code, em):
    """a long per Z80 address in byte-swapped order (the word a ret reads from the Z80 stack): the translated label,
    z80_irq_ret for TOKEN, else z80_badpc (Kung-Fu Master's layout)"""
    labels = {p: 'Z%04X' % p for p in code if p not in em.no_entry}
    labels[TOKEN] = 'z80_irq_ret'
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
