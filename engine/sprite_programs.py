"""Generated sprite code for 16-pixel-wide sprite rows, after stefastbobs2 (main5.s draw_bob_0..f) and
stedaimakaimura (sprite_compiler.js, create_sprite_code.js); first used by Time Pilot (games/timeplt), the method and
the measurements are in docs/sprite-preparation.md ("Generated code per shape and pass-type pattern").

A shape is a sprite image's opaque masks, one 16-bit word a row (bit 15 the leftmost pixel), as the port draws it
(turned, flipped).  Its rows are grouped by mask (shape_order: the order the port bakes the plane words in, so the
Blitter's source address runs on).  Every row is baked aligned at the left border of its source word (its plane words
shifted left by the row's empty columns, lz = align_of(mask)), as stefastbobs2 stores its <= 16-pixel rows: the row's
skew is then (shift + lz) & 15, and a row whose pixels lie in the second destination word only is a plain one-word
pass there (one source read a plane, no FXSR).  At a shift s every group has a pass type (pass_of):
    'A'  two destination words, NFSR (the row straddles a word border after the shift): END1, END3
    'L'  the first word only: END1 = mask >> s
    'R'  the second word only: END1 = mask << (16 - s); the destination one group (8 bytes) further
Source X increment 0 and Y increment 2 serve all three (one source word a plane; 4 planes in a pass: Y count 4,
destination X increment 8, Y increment 2 (one word) or -6 (two)).  At a side edge on a 16-pixel group boundary
(AGENTS.md) the clipped variants draw one word only (clipped_pass: clip 1 the second word, clip 2 the first; rows
without pixels there skipped, the source stepped over them; clip 1 of a straddling row is the one FXSR pass left).

programs() makes per shape 3 x 16 variants (clip 0-2, shift 0-15): the code (per shape and pattern of pass types,
shared by content) and a stream of end masks and control words (shared by content), plus the damage (the drawn lines
and words).  The code writes the Y increment and the X count only where the type changes, the control word (skew,
NFSR / FXSR; the write starts the pass) from the stream at each group's first pass, steps the destination's low word
by immediates, starts the group's other rows with a byte write; it runs with these registers (the port's draw routine sets
them, keeping them from sprite to sprite where it can):
    d0  the destination's low word (row 0, the sprite's first word)      a0  the stream (consumed)
    d1  4 (Y count: the planes)    d2  $C0 (start, HOG)    d4  the line's bytes (160)
    a1 END1   a6 END3   a3 destination Y increment   a5 Y count   a4 destination address + 2   a2 control
and clobbers d0 and a0 only.  The X count is written as BLT_XC (an absolute word: the port defines it).  The caller
sets the source address (the baked, aligned plane words), the destination's high word (a long write), HOP 2 / OP 3 and
the increments, and rejects 64 KB crossings (the low word steps).
"""

FXSR, NFSR = 0x80, 0x40


def shape_order(masks):
    """the opaque rows grouped by their mask, groups in order of their first row: [[rows of a mask], ...]"""
    groups = {}
    for r, m in enumerate(masks):
        if m:
            groups.setdefault(m, []).append(r)
    return sorted(groups.values(), key=lambda g: g[0])


def align_of(mask):
    """the row's empty columns at the left: its plane words are baked shifted left by this"""
    return 16 - mask.bit_length()


def pass_of(mask, s):
    """(type, END1, END3, X count, destination Y increment, control) of a 16-pixel row shifted by s, its source word
    aligned (align_of)"""
    t = s + align_of(mask)
    left, right = mask >> s, (mask << (16 - s)) & 0xFFFF
    if t >= 16:
        return 'R', right, 0, 1, 2, 0xC000 | (t - 16)
    if not right:
        return 'L', left, 0, 1, 2, 0xC000 | t
    return 'A', left, right, 2, -6, 0xC000 | NFSR | t


def clipped_pass(mask, s, clip):
    """pass_of across a side edge (s > 0): clip 1 the second word only, clip 2 the first; None: no pixels there"""
    t = s + align_of(mask)
    left, right = mask >> s, (mask << (16 - s)) & 0xFFFF
    if clip == 1:
        if not right:
            return None
        if t >= 16:
            return 'R', right, 0, 1, 2, 0xC000 | (t - 16)
        return 'R', right, 0, 1, 2, 0xC000 | FXSR | t      # (straddling: the pre-read is the row's word)
    return ('L', left, 0, 1, 2, 0xC000 | t) if left and t < 16 else None


def programs(shapes, nshapes, line=160, plane_bytes=8, prefix='shp', table='tp_shapes', record='shr',
             stream_sym='tp_sstream', xc_sym='B_XC', stream_mode=False, long_dst=False, clips=3):
    """shapes: {shape id: [row masks] or ([row masks], row map)} -> (assembler lines (text: the code, data: the table and the records), the
    stream's bytes, statistics).  The table: nshapes longs, a record's address or 0.  A record: 48 variants of
    12 bytes (clip * 16 + shift): the code's address, the stream's address, the damage offset (from the destination:
    the first drawn line, + 8 when only the second word is drawn) and the damage size (words a line << 8 | lines; 0:
    nothing drawn).
    stream_mode: smaller, for shapes with many mask groups (Kung-Fu Master's 16-row cells): one routine per shape for
    every shift (its row structure), the stream holding per group all the values that change with the shift (the
    destination step, END1, END3, the destination Y increment, the X count, the control word with the skew; the
    first two words of a group: `add (a0)+,d0`); the clipped variants are not made (their records' code 0: the port
    draws those with its row path).
    clips (not stream mode): 1 makes only the unclipped variants (a record of 16; a port that never clips at a side
    edge - R-Type's stage renderer, whose window edges are not on 16-pixel boundaries).
    long_dst (stream mode only): the destination's whole address in a3 (stepped with adda / lea, written as a long to
    BLT_DST through a4 = BLT_DST), so a sprite may cross a 64 KB boundary (rings larger than 64 KB: Kung-Fu Master);
    the destination Y increment is written as BLT_DYI (an absolute word), d0 is not used."""
    if stream_mode:
        return _stream_programs(shapes, nshapes, line, prefix, table, record, stream_sym, xc_sym, long_dst)
    code, stream = [], bytearray()
    recs = {}
    codes, streams = {}, {}
    for sid, spec in sorted(shapes.items()):
        masks, rowmap = (spec, None) if isinstance(spec, list) else spec
        dr = (lambda r: r) if rowmap is None else (lambda r, m=rowmap: m[r])
        groups = shape_order(masks)
        if not groups:
            continue
        variants = []
        for clip in range(clips):
            for sh in range(16):
                passes = [(clipped_pass(masks[g[0]], sh, clip) if clip and sh else pass_of(masks[g[0]], sh))
                          for g in groups]
                body, blk = [], bytearray()
                prev_dst, prev_dyi, prev_xc = 0, None, None
                skipped = 0
                words, rows = set(), []
                for g, ps in zip(groups, passes):
                    if ps is None:
                        skipped += len(g)
                        continue
                    t, e1, e3, xc, dyi, ctl = ps
                    if skipped:
                        body.append('\tadd.l #%d,B_SRC.w' % (plane_bytes * skipped))
                        skipped = 0
                    words |= {'A': {0, 1}, 'L': {0}, 'R': {1}}[t]
                    rows += [dr(r) for r in g]
                    dst = dr(g[0]) * line + (8 if t == 'R' else 0)
                    d = dst - prev_dst
                    body.append('\tadd d4,d0' if d == line else '\tadd #%d,d0' % d)
                    body.append('\tmove d0,(a4)')
                    if dyi != prev_dyi:
                        body.append('\tmove #%d,(a3)' % dyi)
                        prev_dyi = dyi
                    if xc != prev_xc:
                        body.append('\tmove #%d,%s.w' % (xc, xc_sym))
                        prev_xc = xc
                    body.append('\tmove (a0)+,(a1)')
                    blk += e1.to_bytes(2, 'big')
                    if t == 'A':
                        body.append('\tmove (a0)+,(a6)')
                        blk += e3.to_bytes(2, 'big')
                    body.append('\tmove d1,(a5)')
                    # the control word (skew, NFSR / FXSR; the write starts the pass) from the stream at every group:
                    # the code then depends on the pass types only and is shared as before (where it does not
                    # change, a byte write would save 4 cycles, but the code would split by the rows' alignments)
                    body.append('\tmove (a0)+,(a2)')
                    blk += ctl.to_bytes(2, 'big')
                    for a, b in zip(g, g[1:]):
                        d = (dr(b) - dr(a)) * line
                        body.append('\tadd d4,d0' if d == line else '\tadd #%d,d0' % d)
                        body += ['\tmove d0,(a4)', '\tmove d1,(a5)', '\tmove.b d2,(a2)']
                    prev_dst = dst + (dr(g[-1]) - dr(g[0])) * line
                body.append('\trts')
                key = tuple(body)
                if key not in codes:
                    codes[key] = '%s_%d' % (prefix, len(codes))
                    code += [codes[key] + ':'] + body
                blk = bytes(blk)
                if blk not in streams:
                    streams[blk] = len(stream)
                    stream += blk
                if rows:
                    r0, r1 = min(rows), max(rows)
                    off = r0 * line + (8 if words == {1} else 0)
                    dmg = ((8 if len(words) == 2 else 4) << 8) | (r1 - r0 + 1)
                else:
                    off, dmg = 0, 0
                variants.append((codes[key], streams[blk], off, dmg))
        recs[sid] = variants
    lines = ['\tsection text,code'] + code + ['\tsection data,data', '%s:' % table]
    for sid in range(nshapes):
        lines.append('\tdc.l %s' % ('%s_%03x' % (record, sid) if sid in recs else '0'))
    for sid, variants in sorted(recs.items()):
        lines.append('%s_%03x:' % (record, sid))
        for lab, off, doff, dmg in variants:
            lines.append('\tdc.l %s,%s+%d\n\tdc.w %d,$%04x' % (lab, stream_sym, off, doff, dmg))
    stats = dict(shapes=len(recs), routines=len(codes), code_lines=sum(len(k) + 1 for k in codes),
                 stream_blocks=len(streams), stream_bytes=len(stream))
    return lines, bytes(stream), stats


def _stream_programs(shapes, nshapes, line, prefix, table, record, stream_sym, xc_sym, long_dst=False):
    code, stream = [], bytearray()
    recs = {}
    codes, streams = {}, {}
    for sid, spec in sorted(shapes.items()):
        masks, rowmap = (spec, None) if isinstance(spec, list) else spec
        dr = (lambda r: r) if rowmap is None else (lambda r, m=rowmap: m[r])
        groups = shape_order(masks)
        if not groups:
            continue
        body = []
        for g in groups:
            if long_dst:
                body += ['\tadda.w (a0)+,a3', '\tmove.l a3,(a4)', '\tmove (a0)+,(a1)', '\tmove (a0)+,(a6)',
                         '\tmove (a0)+,BLT_DYI.w']
            else:
                body += ['\tadd (a0)+,d0', '\tmove d0,(a4)', '\tmove (a0)+,(a1)', '\tmove (a0)+,(a6)', '\tmove (a0)+,(a3)']
            body += ['\tmove (a0)+,%s.w' % xc_sym, '\tmove d1,(a5)', '\tmove (a0)+,(a2)']
            for a, b in zip(g, g[1:]):
                d = (dr(b) - dr(a)) * line
                if long_dst:
                    body += ['\tadda.w d4,a3' if d == line else '\tlea %d(a3),a3' % d, '\tmove.l a3,(a4)']
                else:
                    body += ['\tadd d4,d0' if d == line else '\tadd #%d,d0' % d, '\tmove d0,(a4)']
                body += ['\tmove d1,(a5)', '\tmove.b d2,(a2)']
        body.append('\trts')
        key = tuple(body)
        if key not in codes:
            codes[key] = '%s_%d' % (prefix, len(codes))
            code += [codes[key] + ':'] + body
        variants = []
        rows = [dr(r) for g in groups for r in g]
        for sh in range(16):
            blk = bytearray()
            prev_dst = 0
            words = set()
            for g in groups:
                t, e1, e3, xc, dyi, ctl = pass_of(masks[g[0]], sh)
                words |= {'A': {0, 1}, 'L': {0}, 'R': {1}}[t]
                dst = dr(g[0]) * line + (8 if t == 'R' else 0)
                for x in (dst - prev_dst, e1, e3, dyi, xc, ctl):
                    blk += (x & 0xFFFF).to_bytes(2, 'big')
                prev_dst = dst + (dr(g[-1]) - dr(g[0])) * line
            blk = bytes(blk)
            if blk not in streams:
                streams[blk] = len(stream)
                stream += blk
            r0, r1 = min(rows), max(rows)
            off = r0 * line + (8 if words == {1} else 0)
            dmg = ((8 if len(words) == 2 else 4) << 8) | (r1 - r0 + 1)
            variants.append((codes[key], streams[blk], off, dmg))
        variants += [(None, 0, 0, 0)] * 32
        recs[sid] = variants
    lines = ['\tsection text,code'] + code + ['\tsection data,data', '%s:' % table]
    for sid in range(nshapes):
        lines.append('\tdc.l %s' % ('%s_%03x' % (record, sid) if sid in recs else '0'))
    for sid, variants in sorted(recs.items()):
        lines.append('%s_%03x:' % (record, sid))
        for lab, off, doff, dmg in variants:
            lines.append('\tdc.l %s,%s+%d\n\tdc.w %d,$%04x' % (lab or '0', stream_sym, off, doff, dmg))
    stats = dict(shapes=len(recs), routines=len(codes), code_lines=sum(len(k) + 1 for k in codes),
                 stream_blocks=len(streams), stream_bytes=len(stream))
    return lines, bytes(stream), stats


def order_table(all_masks, nrows):
    """per shape (in the order given) nrows bytes: its opaque rows in shape_order's order, $FF after the last"""
    out = bytearray()
    for masks in all_masks:
        rows = [r for g in shape_order(masks) for r in g]
        out += bytes(rows) + bytes([0xFF] * (nrows - len(rows)))
    return bytes(out)
