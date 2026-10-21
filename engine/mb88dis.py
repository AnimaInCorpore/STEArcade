"""MB88xx disassembler (MAME 0.289's mb88dasm.cpp).  python engine/mb88dis.py <rom> [start [end]]"""
import sys

NAMES = ("NOP OUTO OUTP OUT TAY TATH TATL TAS ICY ICM STIC X ROL L ADC AND "
         "DAA DAS INK IN TYA TTHA TTLA TSA DCY DCM STDC XX ROR ST SBC OR "
         "SETR SETC RSTR RSTC TSTR TSTI TSTV TSTS TSTC TSTZ STS LS RTS NEG C EOR").split()


def next_pc(a):
    """the address after a (the 6-bit PC wraps into the next 64-byte page)"""
    return (a & ~0x3f) + 0x40 if (a & 0x3f) == 0x3f else a + 1


def dis(rom, a):
    """(text, length, target or None) of the instruction at a"""
    op = rom[a]
    b = next_pc(a)
    arg = rom[b % len(rom)]
    if op < 0x30:
        return NAMES[op], 1, None
    g = op & 0xfc
    if g in (0x30, 0x34, 0x38):
        return "%s  %d" % (("SBIT", "RBIT", "TBIT")[(g - 0x30) // 4], op & 3), 1, None
    if op == 0x3c:
        return "RTI", 1, None
    if op in (0x3d, 0x3e, 0x3f):
        return "%s   #$%02X" % (("JPA", "EN", "DIS")[op - 0x3d], arg), 2, None
    if g in (0x40, 0x44):
        return "%s  %d" % ("SETD" if g == 0x40 else "RSTD", op & 3), 1, None
    if g == 0x48:
        return "TSTD  %d" % ((op & 3) + 8), 1, None
    if g == 0x4c:
        return "TBA   %d" % (op & 3), 1, None
    if g == 0x50:
        return "XD    %d" % (op & 3), 1, None
    if g == 0x54:
        return "XYD   %d" % ((op & 3) + 4), 1, None
    if op < 0x60:
        return "LXI   #$%X" % (op & 7), 1, None
    if op < 0x70:
        t = ((op & 7) << 8) | arg
        t = ((t >> 6) << 6) | (t & 0x3f)
        return "%s  $%03X" % ("CALL" if op < 0x68 else "JPL ", t), 2, t
    if op < 0x80:
        return "AI    #$%X" % (op & 0xf), 1, None
    if op < 0x90:
        return "LYI   #$%X" % (op & 0xf), 1, None
    if op < 0xa0:
        return "LI    #$%X" % (op & 0xf), 1, None
    if op < 0xb0:
        return "CYI   #$%X" % (op & 0xf), 1, None
    if op < 0xc0:
        return "CI    #$%X" % (op & 0xf), 1, None
    t = (b & ~0x3f) | (op & 0x3f)
    return "JMP   $%03X" % t, 1, t


def listing(rom, start=0, end=None):
    end = len(rom) if end is None else end
    a = start
    out = []
    while a < end:
        text, n, _ = dis(rom, a)
        raw = " ".join("%02X" % rom[x % len(rom)] for x in ([a, next_pc(a)] if n == 2 else [a]))
        out.append("%03X  %-6s %s" % (a, raw, text))
        a = next_pc(a) if n == 1 else next_pc(next_pc(a))
    return "\n".join(out)


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    s = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0
    e = int(sys.argv[3], 16) if len(sys.argv) > 3 else len(data)
    print(listing(data, s, e))
