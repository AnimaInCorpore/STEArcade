"""Specialized STE line blits, following stefastbobs2/main.s.

Code is shared by every colour quad. Keep source rows in their original order so
the existing plane data and the generic 64 KB boundary fallback remain usable.
Register contract: a1 END1, a6 END3, a2 control, a3 destination low word,
a5 Y count, a0 compressed masks; d1=4, d2=$c0, d4=+248/-264.
The code consumes a0 and initializes a6; other registers are preserved.
"""


def program(masks, first, count, skew):
    """Return instructions and changed masks for one shape/skew."""
    code = []
    values = []
    end1 = end3 = width = None
    previous = None
    skipped = 0
    for row in range(first, first + count):
        e1, e3 = masks[row]
        if not (e1 or e3):
            skipped += 1
            continue
        if skipped:
            code.append(f"\tadd.l #{skipped * 8},BLT_SRC_ADDR.w")
            skipped = 0
        if previous is not None:
            gap = row - previous
            code.extend(["\tadd d4,(a3)"] * gap)
            if gap > 1:
                code.append(f"\tadd #{8 * (gap - 1)},(a3)")
        # XCOUNT=1 uses END1 and must clear NFSR: with NFSR=1 its
        # source pipeline has special hardware behaviour (Hatari blitter.c).
        words = 1 if e3 == 0 else 2
        changed_width = words != width
        if changed_width:
            code.append(f"\tmove #{2 if words == 1 else -6},BLT_DST_YINC.w")
            code.append(f"\tmove #{words},BLT_COUNT.w")
            width = words
        if e1 != end1:
            code.append("\tmove (a0)+,(a1)")
            values.append(e1)
            end1 = e1
        if words == 2 and e3 != end3:
            code.append("\tmove (a0)+,(a6)")
            values.append(e3)
            end3 = e3
        code.append("\tmove d1,(a5)")
        if changed_width:
            control = 0xc000 | skew | (0x40 if words == 2 else 0)
            code.append(f"\tmove #${control:04x},(a2)")
        else:
            code.append("\tmove.b d2,(a2)")
        previous = row
    code.append("\trts")
    if values:
        code.insert(0, "\tlea BLT_END3.w,a6")
    return tuple(code), tuple(values)


def emit(prefix, masks, spans):
    """Build code/stream pointer pairs, deduplicating instructions and masks separately."""
    routines, streams, entries = {}, {}, []
    for variant, (first, count) in enumerate(spans):
        for skew in range(16):
            off = (variant * 16 + skew) * 64
            rows = [tuple(int.from_bytes(masks[off + row * 4 + k:off + row * 4 + k + 2], "big")
                          for k in (0, 2)) for row in range(16)]
            code, values = program(rows, first, count, skew)
            if code not in routines:
                routines[code] = f"{prefix}_spr_code_{len(routines)}"
            if values not in streams:
                streams[values] = f"{prefix}_spr_stream_{len(streams)}"
            entries.extend((routines[code], streams[values]))
    lines = ["\tifnd NOSPRITECODE", "\tsection data,data", "\tcnop 0,2",
             f"{prefix}_spr_code:"]
    for start in range(0, len(entries), 8):
        lines.append("\tdc.l " + ",".join(entries[start:start + 8]))
    for values, label in streams.items():
        lines.append(label + ":")
        if values:
            lines.append("\tdc.w " + ",".join(f"${v:04x}" for v in values))
    lines.append("\tsection text,code")
    for code, label in routines.items():
        lines.append(label + ":")
        lines.extend(code)
    lines.append("\tendc")
    return lines
