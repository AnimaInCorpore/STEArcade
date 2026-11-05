"""Isolated optimizations of R-Type's existing native collision/tile routines."""
import argparse
import gzip
import pickle
import re
import subprocess
import sys
import zlib

import native_audit as audit

HERE, ROOT = audit.HERE, audit.ROOT
BUILD = ROOT / "build/rtype/hot_native_audit"
PRODUCTION_BUILD = audit.build
VARIANTS = ("base", "imp", "scan", "bounds_y", "bounds_xy", "tile_math", "tile_local", "tiles", "collision", "combined")
RECORD = False


def tile_math(text):
    start, end = text.index("FG_AT\tmacro"), text.index("nat_fgtile:")
    prefix, suffix, text = text[:start], text[end:], text[start:end]
    # Both cached X bases are multiples of four: mask the sum instead.
    for reg, base in (("d3", "tc_basef"), ("d5", "tc_basebx")):
        old = "\tand.w\t#$FFFC,%s\n\tadd.w\t%s,%s\n\tand.w\t#$10FF,%s" % (reg, base, reg, reg)
        new = "\tadd.w\t%s,%s\n\tand.w\t#$10FC,%s" % (base, reg, reg)
        assert text.count(old) == 1
        text = text.replace(old, new)
    old = """\tbcc.s\t.y\\@
\tmoveq\t#0,d0
.y\\@:\tand.w\t#$FFF8,d0
\tlsl.w\t#5,d0
\tadd.w\td0,d3
\tand.w\t#$3FFF,d3"""
    new = """\tbcs.s\t.y\\@
\tand.w\t#$FFF8,d0
\tlsl.w\t#5,d0
\tadd.w\td0,d3
.y\\@:"""
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = """\tbcc.s\t.by\\@
\tmoveq\t#0,d7
.by\\@:\tand.w\t#$FFF8,d7
\tlsl.w\t#5,d7
\tadd.w\td7,d5\t\t\t; IY
\tand.w\t#$3FFF,d5"""
    new = """\tbcs.s\t.by\\@
\tand.w\t#$FFF8,d7
\tlsl.w\t#5,d7
\tadd.w\td7,d5\t\t\t; IY
.by\\@:\tand.w\t#$3FFF,d5"""
    assert text.count(old) == 1
    return prefix + text.replace(old, new) + suffix


def local_tiles(text):
    start = text.index("\tsection data,data\ntc_kf:")
    text = text[:start] + text[start:].replace("\tsection data,data\ntc_kf:", "\t; Local writable cache words, within PC-relative reach.\ntc_kf:", 1)
    start, end = text.index("FG_AT\tmacro"), text.index("nat_fgtile:")
    body = text[start:end]
    body = re.sub(r"\b(tc_(?:kf|kbx|kby|cxf|cwf|basef|cxb|basebx|byterm|yb))(?=,)", r"\1(pc)", body)
    return text[:start] + body + text[end:]


def collision_imp(body):
    old = "\tmovem.l\td1/d3/d6/d7,-(sp)\n\tcmp.w\td0,d3"
    assert body.count(old) == 1
    body = body.replace(old, "\tcmp.w\td0,d3")
    old = "\tmovem.l\t(sp)+,d1/d3/d6/d7\n\tbra.s\t.rej\n.iov:\tmovem.l\t(sp)+,d1/d3/d6/d7\n\tbra\t.full"
    new = """\tbra .imiss
.iov:\tmove.w d0,d1
\tadd.w 2(a1),d1
\tmove.w d0,d3
\tadd.w (a1),d3
\tmove.w d2,d6
\tadd.w 6(a1),d6
\tmove.w d2,d7
\tadd.w 4(a1),d7
\tbra .full
.imiss:
    ifd SIM
\taddq.l #1,es_nrej+4*\\3
    endc
\tmove.w es_last,d4
\tbeq .r0
\ttst.b (a3,d4.w)
\tbeq .iov
\tmove.w d4,a1
\tmove.w es_lastip,d7
\tbra .rend"""
    assert body.count(old) == 1
    return body.replace(old, new)


def collision_scan(body):
    for label, stop, loop in ((".bl:", ".imp:", ".nx:"), (".ibl:", ".rej:", ".inx:")):
        a, b = body.index(label), body.index(stop)
        part = body[a:b]
        for reg, offset in (("d1", 0), ("d3", 2), ("d6", 4), ("d7", 6)):
            old = "cmp.w\t(a0)+," + reg
            assert part.count(old) == 1
            part = part.replace(old, "cmp.w\t%d(a0),%s" % (offset, reg))
        part = part.replace("\taddq.l\t#2,a0\n", "")
        # The compact improper-scan labels have their ADD on the same line.
        part = part.replace("\taddq.l\t#2,a0", "")
        old = loop + "\tdbf"
        assert part.count(old) == 1
        part = part.replace(old, loop + "\taddq.l #8,a0\n\tdbf")
        body = body[:a] + part + body[b:]
    return body


def bounds(text, xy, imp):
    # The union is a superset of the same ordered, deduplicated player boxes.
    start, end = text.index("es_build:"), text.index("\tsection bss,bss\nes_ok:")
    part = text[start:end]
    part = part.replace("\tclr.w\tes_n", "\tmove.l #$FFFF0000,hot_bounds+4\n" +
                        ("\tmove.l #$FFFF0000,hot_bounds\n" if xy else "") + "\tclr.w\tes_n", 1)
    part = part.replace("\taddq.w\t#1,es_n", "\tbsr hot_bound_add\n\taddq.w\t#1,es_n", 1)
    text = text[:start] + part + text[end:]
    start, end = text.index("ECOLL\tmacro"), text.index("nat_ecoll:")
    body = text[start:end]
    def test(reject):
        result = "\tcmp.w hot_bounds+4,d6\n\tbcs " + reject + "\n\tcmp.w hot_bounds+6,d7\n\tbcc " + reject + "\n"
        if xy:
            result += "\tcmp.w hot_bounds,d1\n\tbcs " + reject + "\n\tcmp.w hot_bounds+2,d3\n\tbcc " + reject + "\n"
        return result
    old = "\tlea\tes_boxes,a0\t\t; the distinct live boxes: none overlapped -> no hit"
    assert body.count(old) == 1
    body = body.replace(old, test(".rej") + old)
    old = ".i4:\tlea\tes_boxes,a0"
    assert body.count(old) == 1
    body = body.replace(old, ".i4:\n" + test(".imiss" if imp else ".hot_irej") + "\tlea es_boxes,a0")
    if not imp:
        old = "\tmovem.l\t(sp)+,d1/d3/d6/d7\n\tbra.s\t.rej"
        assert body.count(old) == 1
        body = body.replace(old, ".hot_irej:\n" + old)
    text = text[:start] + body.replace("bra.s\t.rej", "bra\t.rej") + text[end:]
    helper = "\n\tsection text,code\nhot_bound_add:\n\tlea hot_bounds,a0\n"
    for reg, offset in (("d0", 0), ("d1", 4)) if xy else (("d1", 4),):
        helper += f"""\tmove.l {reg},d2
\tswap d2
\tcmp.w {offset}(a0),d2
\tbcc.s .lo{offset}
\tmove.w d2,{offset}(a0)
.lo{offset}:\tcmp.w {offset + 2}(a0),{reg}
\tbls.s .hi{offset}
\tmove.w {reg},{offset + 2}(a0)
.hi{offset}:
"""
    return text + helper + "\trts\n\tsection bss,bss\n\teven\nhot_bounds: ds.w 4\n\tsection text,code\n"


def build(variant):
    audit.BUILD = BUILD
    prg, mp = PRODUCTION_BUILD("production")
    if variant == "base":
        return prg, mp
    src = prg.parent.with_name(prg.parent.name.replace("_assets", "_source"))
    p = src / "natives.s"
    text = p.read_text()
    if variant in ("imp", "collision", "combined"):
        a, b = text.index("ECOLL\tmacro"), text.index("nat_ecoll:")
        text = text[:a] + collision_imp(text[a:b]) + text[b:]
    if variant in ("scan", "collision", "combined"):
        a, b = text.index("ECOLL\tmacro"), text.index("nat_ecoll:")
        text = text[:a] + collision_scan(text[a:b]) + text[b:]
    if variant in ("bounds_y", "bounds_xy"):
        text = bounds(text, variant == "bounds_xy", False)
    if variant in ("tile_math", "tiles", "combined"):
        text = tile_math(text)
    if variant in ("tile_local", "tiles", "combined"):
        text = local_tiles(text)
    p.write_text(text)
    audit.toolchain.assemble_link("rtype", "rtype.s", "native_logic", str(prg),
                                  ["SIM=1", "STAGE=1", "FADE_SNAP=1"])
    return prg, mp


class Logic(audit.Logic):
    def __init__(self, variant):
        self.variant = variant
        super().__init__(variant)

    def load(self, checkpoint):
        super().load(checkpoint)
        self.record_start, self.recorded = checkpoint["frame"], []

    def frame(self, ports, detailed=False):
        result = super().frame(ports, detailed)
        if RECORD and len(self.recorded) < 96:
            m, s, img = self.mem, self.sym, self.sym["v30_image"]
            rd = lambda a, n: audit.swap(bytes(m.r_block(img + a, n)))
            sv = [m.r16(s["m72_scroll_vbl"] + 2 * k) for k in range(4)]
            sc = [m.r16(s["m72_scroll"] + 2 * k) for k in range(4)]
            off, line = bool(m.r16(s["m72_port02"]) & 8), m.r16(s["m72_raster"]) - 128
            bands = [(0, 255, (sc[1], sc[3]), (sc[0], sc[2]), off)]
            if 0 <= line < 255:
                bands = [(0, line, (sv[1], sv[3]), (sv[0], sv[2]), off),
                         (line + 1, 255, (sc[1], sc[3]), (sc[0], sc[2]), off)]
            state = dict(fg=rd(0xD0000, 0x4000), bg=rd(0xD8000, 0x4000),
                         pal0=rd(0xC8000, 0xC00), pal1=rd(0xCC000, 0xC00),
                         objs=bytes(m.r_block(s["m72_objs"], 0x400)), objs_end=m.r16(s["m72_objs_end"]),
                         bands=bands, recs=bytes(m.r16(img + 0x42D34 + 12 * r) & 255 for r in range(32)))
            self.recorded.append((self.record_start + len(self.recorded), zlib.compress(pickle.dumps(state), 1)))
            if len(self.recorded) == 96:
                path = BUILD / ("pictures_%s_%d.pkl.gz" % (self.variant, self.record_start))
                path.write_bytes(gzip.compress(pickle.dumps(self.recorded), mtime=0))
        return result


def main():
    global RECORD
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=VARIANTS, default="combined")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--starts", default="3000,11000,22000,33000,46500,56000,65000,74000")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--windows", default="")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "build/rtype/native_audit").glob("seed*_frame*.pkl.gz"):
        dest = BUILD / p.name
        if not dest.exists():
            dest.symlink_to(p)
    audit.BUILD, audit.build, audit.Logic = BUILD, build, Logic
    RECORD = args.record
    if args.reference:
        audit.reference(args.variant, args.seed, args.frames, windows=args.windows)
    elif args.benchmark:
        audit.benchmark(args.variant, args.seed, list(map(int, args.starts.split(","))), args.frames)
    else:
        for variant in ("base", args.variant):
            subprocess.run([sys.executable, str(HERE / "hot_native_audit.py"), "--benchmark", "--variant", variant,
                            "--seed", str(args.seed), "--starts", args.starts, "--frames", str(args.frames)] +
                           (["--record"] if args.record else []), check=True)


if __name__ == "__main__":
    main()
