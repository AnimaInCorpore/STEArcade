"""The runtime's tables (build/defender/df_assets.s, included by src/defender.s):

* ste_pal_tab: 256 words, a palette byte -> its STE colour.  The game has 16 pens and the STE 16 colours: every pen is
  an STE index, no fit (docs/colours.md, "Exact where it fits"); the arcade's colour (machine.PALETTE, MAME's
  palette_init) snapped to the STE's 4 bits a gun.
* vcol: per video RAM column (x / 2, 0-151) the byte's offset in a screen line << 16 | the pixel pair's position in
  that byte (0-3) * 1024, or -1 where the column is not shown (x < 12 or x > 303).  The picture's x 12-303 lie at
  screen x + 2 (centred in 320).
* vvals: per position (4) and byte (256) the two pixels' bits in the four plane bytes (plane 0 in the long's top byte:
  movep.l order); the left pixel (high nibble) is the position's higher bit.
* vmask: per position the bits of the other six pixels in each plane byte.
* tvv: df_scan's per position: the vmask long, then the 256 vvals longs.
* terr_tab: df_scan's columns (A = $98 down to 1): the screen offset of the column's byte in a line (-1 where not
  shown) and its tvv table (after the vmask).
* tc0-tc152 (terr_code): df_terrain's columns as code.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import PALETTE, VIS_X
from paths import build_dir

X_SHIFT = 2


def ste_word(c):
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = ((int(v) * 2 + 17) // 34 for v in c)     # (the nearest of the 16 levels)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def vcol():
    out = []
    for col in range(152):
        x = 2 * col
        if not VIS_X[0] <= x <= VIS_X[1] - 1:
            out.append(0xFFFFFFFF)
            continue
        xs = x + X_SHIFT
        off = (xs >> 4) * 8 + ((xs >> 3) & 1)
        out.append((off << 16) | (((xs & 7) >> 1) * 1024))
    return out


def vvals():
    out = []
    for p in range(4):
        for v in range(256):
            hi, lo = v >> 4, v & 15
            long = 0
            for k in range(4):
                b = (((hi >> k) & 1) << (7 - 2 * p)) | (((lo >> k) & 1) << (6 - 2 * p))
                long |= b << (8 * (3 - k))
            out.append(long)
    return out


def vmask():
    out = []
    for p in range(4):
        m = ~(0xC0 >> (2 * p)) & 0xFF
        out.append(m * 0x01010101)
    return out


# The sprite copiers' rectangles (src/defender.s spr_rect): W columns (2 pixels each) by H lines, from an image in bank
# 2's $CC00-$CFFF or zeros.  A column's pixel pair sits at position (column + 1) & 3 of its plane byte; the columns of a
# plane byte form a group.  Per shape, image / zero and the first column's position a routine writes the rectangle's
# lines group by group: a whole group with one movep.l, a group with other pixels as a masked read-modify-write.  a0 =
# spr_p + (image - $CC00) * 4 (spr_p: per position 1024 longs, an image byte's two pixels in the four plane bytes),
# a1 / a2 / a3 = the groups' screen bytes on the first line, d5 = 0.  Uses d6, d7.
SPR_SHAPES = ((2, 8), (4, 8), (5, 8), (5, 6), (6, 6), (8, 6), (6, 4))


def spr_groups(w, p0):
    groups, cur = [], []
    for k in range(w):
        p = (p0 + k) & 3
        if p == 0 and cur:
            groups.append(cur)
            cur = []
        cur.append((k, p))
    groups.append(cur)
    return groups


def spr_code():
    vm = vmask()
    out = ['\tsection text,code']
    for w, h in SPR_SHAPES:
        for img in (1, 0):
            name = 'spr_%s%d%d' % ('i' if img else 'z', w, h)
            for p0 in range(4):
                out.append('%s_%d:' % (name, p0))
                for r in range(h):
                    for gi, g in enumerate(spr_groups(w, p0)):
                        ar, d = 'a%d' % (gi + 1), r * 160
                        keep = 0xFFFFFFFF
                        for k, p in g:
                            keep &= vm[p]
                        if img:
                            for i, (k, p) in enumerate(g):
                                out.append('\t%s.l\t%d(a0),d6' % ('move' if i == 0 else 'or', p * 4096 + (k * h + r) * 4))
                        if len(g) == 4:
                            out.append('\tmovep.l\t%s,%d(%s)' % ('d6' if img else 'd5', d, ar))
                        else:
                            out.append('\tmovep.l\t%d(%s),d7' % (d, ar))
                            out.append('\tand.l\t#$%08X,d7' % keep)
                            if img:
                                out.append('\tor.l\td6,d7')
                            out.append('\tmovep.l\td7,%d(%s)' % (d, ar))
                out.append('\trts')
    out.append('\tsection data,data')
    for w, h in SPR_SHAPES:
        for img in (1, 0):
            name = 'spr_%s%d%d' % ('i' if img else 'z', w, h)
            out.append('spr_t_%s:\tdc.l\t%s' % (name[4:], ','.join('%s_%d' % (name, p0) for p0 in range(4))))
    return out


# df_terrain's columns (src/defender.s), generated: column k (A = $98 - k) with its screen offset, mask and position
# baked in.  In: d0 / d2 upper words 0, a2 = Y ($BE20 + 2k), a3 = tline, a4 = df_mem, a5 = the stream, a6 = vv_tab.  A
# column at the same address with the same bytes is passed; else the old bytes the draw does not overwrite are erased
# (a zero where not 0; another column's: terr_oth) and the new ones set where they differ, a line's two pixels with
# one movep read-modify-write, both lines' addresses from one movem of tline.  A column not shown: terr_hid.
def terr_code():
    vc, vm = vcol(), vmask()
    out, cold = ['\tsection text,code'], []
    for k in range(152):
        a = 0x98 - k
        e = vc[a] if a < 152 else 0xFFFFFFFF
        L = 'tc%d' % k
        out += ['%s:' % L, '\tmove.w\t#$%04X,d0' % (a << 8), '\tmove.b\t(a5)+,d0', '\tmove.b\t(a5)+,d5',
                '\tmove.b\t(a5)+,d4', '\tmove.w\t(a2),d2', '\tmove.w\td0,(a2)+']
        if e == 0xFFFFFFFF:
            out.append('\tbsr\tterr_hid')
            continue
        off, pos = e >> 16, (e & 0xFFFF) >> 10
        mask = '#$%08X' % vm[pos]

        def erase(addr, ar, x):
            return ['\ttst.b\t%s' % addr, '\tbeq.s\t%s' % x, '\tclr.b\t%s' % addr,
                    '\tmovep.l\t%d(%s),d7' % (off, ar), '\tand.l\t%s,d7' % mask, '\tmovep.l\td7,%d(%s)' % (off, ar)]

        def put(dr, addr, ar, x):
            return ['\tcmp.b\t%s,%s' % (addr, dr), '\tbeq.s\t%s' % x, '\tmove.b\t%s,%s' % (dr, addr),
                    '\tmoveq\t#0,d6', '\tmove.b\t%s,d6' % dr, '\tlsl.w\t#4,d6',
                    '\tmovep.l\t%d(%s),d7' % (off, ar), '\tand.l\t%s,d7' % mask,
                    '\tor.l\t%d(a6,d6.w),d7' % (pos * 4), '\tmovep.l\td7,%d(%s)' % (off, ar)]
        out += ['\tcmp.w\td2,d0', '\tbne\t%s_m' % L, '\tcmp.b\t(a4,d0.l),d5', '\tbne\t%s_n' % L,
                '\tcmp.b\t1(a4,d0.l),d4', '\tbeq\ttc%d' % (k + 1), '\tbra\t%s_n' % L,
                '%s_m:' % L, '\tmove.w\td2,d3', '\teor.w\td0,d3', '\tcmp.w\t#$100,d3', '\tbhs\t%s_o' % L,
                '\tmoveq\t#0,d1', '\tmove.b\td2,d1', '\tadd.w\td1,d1', '\tadd.w\td1,d1',
                '\tmovem.l\t(a3,d1.w),a0/a1', '\tmove.w\td0,d3', '\tsub.w\td2,d3',
                '\tsubq.w\t#1,d3', '\tbeq\t%s_e' % L]
        out += erase('1(a4,d2.l)', 'a1', '%s_f' % L)
        out += ['%s_f:' % L, '\taddq.w\t#2,d3', '\tbeq\t%s_n' % L, '%s_e:' % L]
        out += erase('(a4,d2.l)', 'a0', '%s_n' % L)
        out += ['%s_n:' % L, '\tmoveq\t#0,d1', '\tmove.b\td0,d1', '\tadd.w\td1,d1', '\tadd.w\td1,d1',
                '\tmovem.l\t(a3,d1.w),a0/a1']
        out += put('d5', '(a4,d0.l)', 'a0', '%s_p' % L)
        out += ['%s_p:' % L]
        out += put('d4', '1(a4,d0.l)', 'a1', 'tc%d' % (k + 1))
        cold += ['%s_o:' % L, '\tbsr\tterr_oth', '\tbra\t%s_n' % L]
    out += ['tc152:', '\tbra\tterr_done'] + cold
    return out



def build():
    lines =['; generated by games/defender/tools/assets.py', '\tsection data,data', '\teven', 'ste_pal_tab:']
    words = [ste_word(PALETTE[v]) for v in range(256)]
    for i in range(0, 256, 16):
        lines.append('\tdc.w ' + ','.join('$%03X' % w for w in words[i:i + 16]))
    for name, data in (('vcol', vcol()), ('vvals', vvals()), ('vmask', vmask())):
        lines.append(name + ':')
        for i in range(0, len(data), 8):
            lines.append('\tdc.l ' + ','.join('$%08X' % w for w in data[i:i + 8]))
    lines.append('tvv:')                 # df_scan: per position its vmask, then its vvals (256 longs)
    vv, vm = vvals(), vmask()
    for pos in range(4):
        lines.append('\tdc.l $%08X' % vm[pos])
        for i in range(0, 256, 8):
            lines.append('\tdc.l ' +','.join('$%08X' % w for w in vv[pos * 256 + i:pos * 256 + i + 8]))
    lines.append('terr_tab:')            # df_scan: per column A = $98 .. 1 the screen offset (-1: not shown), its tvv
    vc = vcol()
    for a in range(0x98, 0, -1):
        e = vc[a] if a < 152 else 0xFFFFFFFF
        if e == 0xFFFFFFFF:
            lines.append('\tdc.l -1,tvv+4')
        else:
            pos = (e & 0xFFFF) >> 10
            lines.append('\tdc.l %d,tvv+%d' % (e >> 16, pos * 1028 + 4))
    lines += spr_code()
    lines += terr_code()
    (build_dir('defender') / 'df_assets.s').write_text('\n'.join(lines) + '\n')
    vv = vvals()                     # [position][byte] -> vv_tab[byte * 4 + position] (vput's index: byte * 16 + pos * 4)
    order = [vv[p * 256 + v] for v in range(256) for p in range(4)]
    (build_dir('defender') / 'df_vv.s').write_text(
        ''.join('\tdc.l ' + ','.join('$%08X' % w for w in order[i:i + 8]) + '\n' for i in range(0, len(order), 8)))


if __name__ == '__main__':
    build()
