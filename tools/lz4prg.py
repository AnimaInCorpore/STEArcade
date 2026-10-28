#!/usr/bin/env python3
"""Pack a TOS program with LZ4 into a self-unpacking TOS program (tools/lz4stub.s unpacks it on the ST).

    python tools/lz4prg.py IN.PRG OUT.PRG        (or: lz4prg.pack(data) -> (packed, info))

The text and data of the program and its relocation table are packed as one LZ4 frame (lz4 -12, linked blocks,
no checksums; the lz4 command must be installed).  The packed program's text is the stub, its data the frame, its
BSS so large that TOS gives it the memory of the whole layout below.  Offsets are from the text start (T):

    0 .. S          the stub (code + parameters), as loaded
    S .. S+P        the frame, as loaded (the program's data segment)
    0 .. U          the game's text + data + relocation table, unpacked in place over all of the above
    D .. D+P        the frame, moved up so that unpacking never overtakes it (D from simulating the depacker)
    X .. X+S        the stub's copy that runs: above the frame's copy, above the game's text + data + BSS

At start the stub copies itself to X and jumps there, moves the frame to D (from the end down), unpacks it to T,
relocates the game, clears from its BSS start to the end of what was used (TOS cleared the rest: it is the packed
program's BSS), sets the basepage's text / data / BSS fields to the game's and jumps to T with the stack as TOS
left it.  The game then needs at most S more bytes than unpacked (the stub's copy) unless the frame does not fit
in its BSS.

pack() simulates the stub's depacker on the frame byte for byte, with its 16-bit counters, and refuses a frame it
would decode wrongly; the result must equal the input.
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from paths import VASM  # noqa: E402

STUB_SRC = ROOT / "tools" / "lz4stub.s"
PARAMS = 8          # longs at the stub's end: D, X, P, TLEN, DLEN, BLEN, CLEAR_END, stub length


def parse_prg(data):
    if data[:2] != b"\x60\x1a":
        raise ValueError("not a TOS program")
    tlen, dlen, blen, slen, _res, flags, absflag = struct.unpack(">IIIIIIH", data[2:28])
    body = data[28:28 + tlen + dlen]
    reloc = b"\0\0\0\0"
    if absflag == 0:
        r = 28 + tlen + dlen + slen
        first = struct.unpack(">I", data[r:r + 4])[0]
        if first:
            end = data.index(b"\0", r + 4) + 1
            reloc = data[r:end]
    return dict(tlen=tlen, dlen=dlen, blen=blen, flags=flags, body=body, reloc=reloc)


def lz4_frame(raw):
    with tempfile.TemporaryDirectory() as t:
        i, o = Path(t) / "in", Path(t) / "out"
        i.write_bytes(raw)
        subprocess.run(["lz4", "-q", "-f", "-12", "-BD", "--no-frame-crc", "--no-content-size", str(i), str(o)],
                       check=True)
        return o.read_bytes()


def simulate(frame, size):
    """The stub's lz4_decode on frame, as the 68000 runs it.  Returns (output, margin): margin is the least
    distance D (frame start - output start) at which no write lands on a frame byte not yet read."""
    if frame[:4] != b"\x04\x22\x4d\x18":
        raise ValueError("not an LZ4 frame")
    flg = frame[4]
    if flg & 0x1d or (flg >> 6) != 1:          # dictionary id, content size, block checksums: the stub skips 7 bytes
        raise ValueError("LZ4 frame flags %02x: the stub expects a 7-byte header without block checksums" % flg)
    out = bytearray()
    i = 7
    need = 0                                     # max over writes of (output position + 1 - input position)

    def wrote():
        nonlocal need
        need = max(need, len(out) - i)

    while True:
        bsize = struct.unpack("<I", frame[i:i + 4])[0]
        i += 4
        if bsize == 0:
            break
        if bsize & 0x80000000:
            n = bsize & 0x7fffffff
            for _ in range(n):
                out.append(frame[i]); i += 1; wrote()
            continue
        end = i + bsize
        while True:
            tok = frame[i]; i += 1
            lit = tok >> 4
            if lit:
                if lit == 15:
                    while True:
                        b = frame[i]; i += 1
                        lit += b
                        if lit > 0xfffff:
                            raise ValueError("a literal run over 1 MB: the stub's dbra counter overflows")
                        if b != 255:
                            break
                for _ in range(lit):
                    out.append(frame[i]); i += 1; wrote()
                if i == end:
                    break
            elif i == end:                       # (a token without literals is followed by a match)
                raise ValueError("empty last sequence")
            off = frame[i] | frame[i + 1] << 8; i += 2
            ml = tok & 15
            if ml == 15:
                while True:
                    b = frame[i]; i += 1
                    ml += b
                    if ml > 0xfffff:
                        raise ValueError("a match over 1 MB: the stub's dbra counter overflows")
                    if b != 255:
                        break
            if off == 0 or off > len(out):
                raise ValueError("bad match offset")
            for _ in range(ml + 4):
                out.append(out[-off])
            wrote()
            if len(out) > size:
                raise ValueError("output longer than the input")
    return bytes(out), need


def stub_code():
    with tempfile.TemporaryDirectory() as t:
        o = Path(t) / "stub.bin"
        r = subprocess.run([VASM, "-Fbin", "-quiet", "-o", str(o), str(STUB_SRC)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("vasm: " + r.stdout + r.stderr)
        return o.read_bytes()


def align(n, a=4):
    return (n + a - 1) & -a


def pack(data):
    p = parse_prg(data)
    raw = p["body"] + p["reloc"]
    frame = lz4_frame(raw)
    out, need = simulate(frame, len(raw))
    if out != raw:
        raise ValueError("the simulated depacker's output differs from the input")
    frame += b"\0" * (align(len(frame)) - len(frame))
    code = stub_code()
    S = align(len(code) + 4 * PARAMS)
    P = len(frame)
    U = len(raw)
    game_end = p["tlen"] + p["dlen"] + p["blen"]
    D = align(max(need, S))                      # (>= S: the frame moves up, copied from its end down)
    X = align(max(game_end, U, D + P))
    clear_end = align(max(U, D + P))             # (D + P >= S + P: covers the stub and the frame as loaded)
    params = struct.pack(">8I", D, X, P, p["tlen"], p["dlen"], p["blen"], clear_end, S)
    text = code + b"\0" * (S - 4 * PARAMS - len(code)) + params
    bss = X - P                                  # text + data + BSS = X + S: TOS reserves up to the copy's end
    header = struct.pack(">HIIIIIIH", 0x601a, S, P, bss, 0, 0, p["flags"], 0)
    packed = header + text + frame + b"\0\0\0\0"  # (no relocations: the stub is position independent)
    info = dict(file=len(data), packed=len(packed), load=game_end + 256, packed_load=X + S + 256, frame=P,
                margin=need, D=D, X=X)
    return packed, info


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    packed, info = pack(Path(sys.argv[1]).read_bytes())
    Path(sys.argv[2]).write_bytes(packed)
    print("%s: %d -> %d bytes; memory %d -> %d" % (sys.argv[2], info["file"], info["packed"], info["load"],
                                                  info["packed_load"]))


if __name__ == "__main__":
    main()
