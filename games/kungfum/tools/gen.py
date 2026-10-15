"""Kung-Fu Master: the main Z80 program (32 KB, flat) translated to 68000 code.

    python gen.py   ->  build/kungfum/code_kungfum.s (+ translation.json)

Coverage: build/kungfum/cover<seed>.pkl (ref/cover.py, the port's schedule).  The runtime (src/kungfum.s) delivers
the IRQ (RST 38) at the idle hooks (machine.KungFuPort.HOOKS: spin loops on RAM the IRQ changes, the play loop's
head): a hook calls z80_hook (d7 = pc), which returns to go on or delivers the IRQ with TOKEN as its return address.
The I/O ports: `in a,(n)` reads io_ports + n (SYSTEM, P1, P2, DSW1, DSW2: the runtime keeps them), `out (0),a` is
the sound command (kf_sound, which keeps the flags), `out (1),a` the flip latch.  The stores to the tile RAM
(D000-DFFF, the coverage's write sites) mark the 64-byte row they hit in tile_rows (32 bytes: the code and attribute
halves of a row share a mark) through kf_mark_* routines that keep the flags; the renderer compares only the marked
rows with its copy.  The sprite RAM (C000-C0FF) and the scroll (A000 / B000) are plain stores into the block.
"""
from pathlib import Path
import sys
import pickle
import json
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import z80x
import discover
from translate import compile_code
from paths import build_dir, require_coverage, EXTRACTED
from machine import KungFuPort

BUILD = build_dir('kungfum')
HOOKS = sorted(KungFuPort.HOOKS)
TOKEN = KungFuPort.TOKEN
SEEDS = range(1, 14)
# Jump tables whose entries the coverage did not all run (the porting guide: every translated `jp (hl)`'s table):
# (table, entries).  28DC: the 5th floor's boss (`ld hl,$28DC; jp $1F23`, indexed by (ix+1)), 11 words up to the code
# at 28F2.  (The others: 0156 by the state E000 < 11 (9 words, the states 9 and 10 never come), 1897 (11 words, three of
# them outside the ROM: never used), 1E84 / 1F0B / 2FF7 / 4DBC / 4DC2 run whole; 77B1 is the service mode's, not
# translated.)
TABLES = [(0x28DC, 11)]


def image():
    rom = (EXTRACTED / 'kungfum' / 'a-4e-c.bin').read_bytes() + (EXTRACTED / 'kungfum' / 'a-4d-c.bin').read_bytes()
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage('kungfum', ['cover%d.pkl' % s for s in SEEDS])
    pcs, jumps, writes, io = set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ('cover%d.pkl' % s)).read_bytes())
        pcs |= d['pcs']
        jumps |= d['jumps']
        writes |= d['writes']
        io |= d['io']
    return pcs, jumps, writes, io


class KEmitter(z80x.Emitter):
    def __init__(self, *a, tile_sites=None, **k):
        super().__init__(*a, **k)
        self.tile_sites = tile_sites or {}

    def x_in(self, ins):
        dst, src = ins.ops
        if dst != ('r8', 'a') or src[0] != 'port':
            raise z80x.Unsupported('in ' + ins.text)
        self.e('move.b io_ports+%d,d0' % (src[1] & 0xff))   # (in a,(n): no flags; the move's are not Z80 flags)

    def x_out(self, ins):
        dst, src = ins.ops
        if src != ('r8', 'a') or dst[0] != 'port':
            raise z80x.Unsupported('out ' + ins.text)
        port = dst[1] & 0xff
        if port == 0:
            self.e('bsr kf_sound')            # (keeps the flags: d0 = the command)
        elif port == 1:
            self.e('move.b d0,io_flip')
        else:
            raise z80x.Unsupported('out port %d' % port)

    def x_cpdr(self, ins):
        """z80x's cpir going down (5768, 57E7: a byte searched in a ROM table)"""
        loop = self.new_label()
        end = self.new_label()
        self.e("move.w d1,d5")
        self.e("ror.w #8,d5")
        self.lines.append(loop + ":")
        self.e("cmp.b %s,d0" % self.ind("d3"))
        self.e("move sr,d7")
        self.e("subq.w #1,d3")
        self.e("subq.w #1,d5")
        self.e("beq.s %s" % end)
        self.e("btst #2,d7")
        self.e("beq.s %s" % loop)
        self.lines.append(end + ":")
        self.e("ror.w #8,d5")
        self.e("move.w d5,d1")
        lo = self.lo
        if lo & (z80x.S | z80x.Z):
            m = (0x08 if lo & z80x.S else 0) | (0x04 if lo & z80x.Z else 0)
            self.e("eor.b d6,d7")
            self.e("and.b #$%02X,d7" % m)
            self.e("eor.b d7,d6")
        if lo & z80x.H:
            raise z80x.Unsupported("H after cpdr")
        if lo & z80x.N:
            self.e("ori.b #$40,d6")

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        super().emit_ins(pc, live_out_override, with_label)
        mark = self.tile_sites.get(pc)
        if mark:
            self.e(mark)                      # (the marks keep the flags)


def tile_marks(code, writes):
    """pc -> the line that marks the tile RAM row its store hit (a routine per address register; static stores mark
    their row directly; block moves mark every row)"""
    out = {}
    for pc in sorted({pc for pc, a in writes if 0xD000 <= a < 0xE000}):
        ins = code.get(pc)
        if ins is None:
            continue
        if ins.mn in ('ldir', 'lddr', 'ldi', 'ldd'):
            out[pc] = 'bsr kf_mark_all'
            continue
        dst = ins.ops[0] if ins.ops else None
        if ins.mn in ('push', 'call', 'rst') or dst is None:
            raise RuntimeError('tile RAM write by %04X %s' % (pc, ins.text))
        if dst[0] == 'ind16':
            out[pc] = 'st tile_rows+%d' % ((dst[1] & 0x7ff) >> 6)
            if ins.mn == 'ld' and ins.ops[1][0] == 'r16':          # (ld (nn),rr: two bytes)
                out[pc] += '\n\tst tile_rows+%d' % (((dst[1] + 1) & 0x7ff) >> 6)
        elif dst[0] == 'ind' and dst[1] in ('hl', 'de', 'bc', 'ix', 'iy') and ins.mn in (
                'ld', 'inc', 'dec', 'set', 'res', 'rlc', 'rrc', 'rl', 'rr', 'sla', 'sra', 'srl', 'sll', 'rld', 'rrd'):
            if dst[1] in ('ix', 'iy'):
                out[pc] = 'pea %d.w\n\tbsr kf_mark_%s\n\taddq.l #4,a7' % (dst[2], dst[1])
            else:
                out[pc] = 'bsr kf_mark_%s' % dst[1]
        elif ins.mn == 'ex' and dst == ('ind', 'sp', 0):
            raise RuntimeError('tile RAM write by %04X %s' % (pc, ins.text))
        else:
            raise RuntimeError('tile RAM write by %04X %s (form)' % (pc, ins.text))
    return out


def generate():
    rom = image()
    pcs, jumps, writes, io = coverage()
    roots = {0, 0x38} | set(HOOKS) | jumps
    for t, n in TABLES:
        roots |= {rom[t + 2 * k] | rom[t + 2 * k + 1] << 8 for k in range(n)}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < 0x8000}
        missing = discover.skip_returns(rom, code, lambda pc: pc < 0x8000, cache) - set(code)
        if not missing:
            break
        roots |= missing
    cfg = z80x.Config(mode='signed', block=0x10000, table_entries=0x10000, iyaddr=0xF7F0, fshadow=0xF7F2,
                      io_read_redirect={}, write_hooks=[], nmi_token=TOKEN, token_sym='z80_irq_ret',
                      rst28_tables=False, bit_s=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    marks = tile_marks(code, writes)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=KEmitter, ijmp_flags=True, flags_at=set(HOOKS),
                      tile_sites=marks)
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError('observed instructions cannot be translated: %s' % seen)
    out = ['; generated: Kung-Fu Master main Z80 -> 68000 (games/kungfum/tools/gen.py)', '\tsection text,code']
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
    z80_irq_ret for TOKEN, else z80_badpc (Commando's layout)"""
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
    (BUILD / 'code_kungfum.s').write_text(text)
    (BUILD / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print({k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')}, len(report['unsupported']),
          'unsupported')
