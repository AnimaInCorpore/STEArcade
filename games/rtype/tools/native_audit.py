"""Production native checks, isolated experiments and hot-code profiles.

The pre-integration generator and natives are pinned to BASELINE_REV; production
uses the current generator output and native source without prototype patches.
Checkpoints are produced by the historical baseline translation. They accelerate
profiling and controlled before/after tests; they do not replace reference
lock-step checks from boot or constitute independent whole-game equivalence.
"""
import argparse
import bisect
import collections
import gzip
import hashlib
import json
import os
import pickle
import random
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "engine"), str(HERE.parent / "ref")]
import cover
import snapshot
import toolchain
from logic_test import REGIONS, DREG, swap, ref_region
from machine68k import Register as R
from sim import Sim, TRAP1

BUILD = ROOT / "build/rtype/native_audit"
BASELINE_REV = "958043317915566359fb72ff721d162a82513193"
GENERATED = ("code_main.s", "tables_main.s", "gen_info.s", "gen_info.json", "rom_image.bin")


def historical(path):
    """The measured pre-integration source, independent of working-tree changes."""
    return subprocess.check_output(["git", "show", BASELINE_REV + ":" + path], cwd=ROOT).decode()


def baseline_translation():
    """Regenerate the old dispatch from its generator; retain only compressed outputs."""
    cache = BUILD / ("baseline_" + BASELINE_REV[:7])
    cache.mkdir(parents=True, exist_ok=True)
    if not all((cache / (name + ".gz")).exists() for name in GENERATED):
        for p in (ROOT / "build/rtype").glob("cover_*.pkl"):
            dest = cache / p.name
            if not dest.exists():
                dest.symlink_to(p)
        module = types.ModuleType("native_audit_baseline_gen")
        module.__file__ = str(HERE / "gen.py")
        exec(compile(historical("games/rtype/tools/gen.py"), module.__file__, "exec"), module.__dict__)
        module.build_dir = lambda game: cache
        module.generate()
        for name in GENERATED:
            p = cache / name
            (cache / (name + ".gz")).write_bytes(gzip.compress(p.read_bytes(), mtime=0))
            p.unlink()
        for p in cache.glob("cover_*.pkl"):
            p.unlink()
    return cache


def build(variant):
    tag = variant + "_" + str(os.getpid())
    assets, src = BUILD / (tag + "_assets"), BUILD / (tag + "_source")
    assets.mkdir(parents=True, exist_ok=True)
    src.mkdir(exist_ok=True)
    for p in (ROOT / "build/rtype").iterdir():
        if p.is_file():
            dest = assets / p.name
            if not dest.exists():
                dest.symlink_to(p)
    for p in (HERE.parent / "src").glob("*.s"):
        shutil.copy2(p, src / p.name)
    if variant != "production":
        (src / "natives.s").write_text(historical("games/rtype/src/natives.s"))
        cache = baseline_translation()
        for name in GENERATED:
            p = assets / name
            if p.exists() or p.is_symlink():
                p.unlink()
            p.write_bytes(gzip.decompress((cache / (name + ".gz")).read_bytes()))
    if variant in ("fade", "fade_cache", "combined"):
        p = src / "natives.s"
        text = p.read_text()
        old = "\tmove.b\t(a0,d0.l),d0\n\tmove.w\td0,(a1)"
        assert text.count(old) == 1
        text = text.replace(old, "\tmove.b\t(a0,d0.l),d0\n\tand.w #$00FF,d0\n\tmove.w\td0,(a1)")
        p.write_text(text)
    if variant == "fade":
        p = src / "natives.s"
        text = p.read_text()
        old = ".slow\\@:\tlea\t(a3,d3.l),a0"
        assert text.count(old) == 1
        text = text.replace(old, r""".slow\@:
	cmp.l #v30_image+$3B000,a2
	bne.s .original\@
	bsr nat_nf_copy
	bra .tail\@
.original\@:	lea (a3,d3.l),a0""")
        text += "\n" + (HERE / "native_fade.s").read_text()
        p.write_text(text)
    if variant in ("object", "combined"):
        p = src / "natives.s"
        text = p.read_text()
        body = text.split("EMIT1\tmacro", 1)[1].split("\tendm", 1)[0]
        body = re.sub(r"\tNEXIT\s+\\1,R0201A", "", body)
        # Inline the emitter's leaf entry: its emulated CALL occupies two bytes,
        # so its saved DS0 word is four bytes below the caller's original SP.
        body = body.replace("-2(a5)", "-4(a5)")
        assert "\\1" not in body
        text += "\nNH_EMIT macro" + body + "\tendm\n" + (HERE / "native_object.s").read_text()
        # Reading a definition's x/y offsets is unused in the object-list build.
        old = "\tmove.w\t\\1(a2,d3.l),d7\t\t; (y offset << 8 | x offset)\n    ifnd SPRITE_LIST\n"
        assert text.count(old) == 1
        text = text.replace(old, "    ifnd SPRITE_LIST\n\tmove.w\t\\1(a2,d3.l),d7\n")
        p.write_text(text)
        code = assets / "code_main.s"
        original = code.read_text()
        original, count = re.subn(r"^(R0E9CD:[^\n]*\n)", r"\1\tjmp nat_nh_e5cd\nR0E9CD_t:\n", original, flags=re.M)
        assert count == 1
        code.write_text(original)
    if variant in ("clear", "combined"):
        p = src / "natives.s"
        p.write_text(p.read_text() + "\n" + (HERE / "native_clear.s").read_text())
        code = assets / "code_main.s"
        original = code.read_text()
        if code.is_symlink():
            code.unlink()
        for label, target in (("R0EC73", "nat_nc_tail"), ("R0EC90", "nat_nc_fg"), ("R0ECAD", "nat_nc_bg")):
            original, count = re.subn(r"^(" + label + r":[^\n]*\n)", r"\1\tjmp " + target + "\n" + label + "_t:\n", original, flags=re.M)
            assert count == 1
        code.write_text(original)
    toolchain.src_dir = lambda game: src
    toolchain.build_dir = lambda game: assets
    prg = assets / "RTYPE.PRG"
    toolchain.assemble_link("rtype", "rtype.s", "native_logic", str(prg), ["SIM=1", "STAGE=1", "FADE_SNAP=1"])
    return prg, assets / "native_logic.map"


class Logic:
    def __init__(self, variant="base"):
        self.prg, mp = build(variant)
        self.s = Sim(str(self.prg), ram_kib=16384, run_dir=self.prg.parent)
        self.s.mem.set_trace_mode(False)
        self.mem, self.cpu = self.s.mem, self.s.cpu
        assert json.loads((ROOT / "build/rtype/gen_info.json").read_text())["idle_flags"] == 0
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(mp).items()}
        self.run_to()
        code_names = {m[1] for m in re.finditer(r"0x[0-9a-f]{8} (\S+?): \S+ reloc", mp.read_text())}
        labels = sorted((v, k) for k, v in self.sym.items() if k in code_names and
                        (re.fullmatch(r"R[0-9A-F]{5}", k) or not k.startswith("R")))
        self.addresses, self.labels = zip(*labels)
        self.prof = collections.Counter()
        self.frames = []
        self.watch = {}

    def run_to(self):
        cycles = 0
        while True:
            cycles += self.cpu.execute(10000).cycles
            pc = self.cpu.r_pc()
            if pc == self.sym["sim_wait"]:
                return cycles
            if pc == TRAP1:
                self.s.gemdos()
            elif pc == self.sym["sim_badpc"]:
                raise RuntimeError("badpc %05X" % self.mem.r32(self.sym["badpc"]))
            elif pc == 0x600:
                raise RuntimeError("68000 exception")

    def initialize(self, m):
        img, ctx = self.sym["v30_image"], self.sym["ctx_main"]
        for _, base, size in REGIONS:
            self.mem.w_block(img + base, swap(ref_region(m, base, size)))
        self.mem.w_block(self.sym["m72_spritebuf"], swap(bytes(m.spritebuf)))
        c = m.main.core.cpu
        for k in range(4):
            self.mem.w16(ctx + 2 * k, c.sr[k])
        for k, value in enumerate((c.ie != 0, c.df != 0, not snapshot.PAR[c.pv & 255], c.av)):
            self.mem.w8(ctx + 8 + k, (255 if value else 0) if k < 2 else int(value))
        for k, (_, i) in enumerate(DREG):
            self.mem.w32(ctx + 16 + 4 * k, c.r[i])
        bases = [img + (c.sr[k] << 4) for k in (0, 3, 2)]
        for k, value in enumerate(bases + [bases[2] + c.sp]):
            self.mem.w32(ctx + 44 + 4 * k, value)
        f = c.flags
        self.mem.w16(ctx + 60, (f & 1) | (2 if f & 0x800 else 0) | (4 if f & 0x40 else 0) | (8 if f & 0x80 else 0))
        for k, value in enumerate((m.scrolly[0], m.scrollx[0], m.scrolly[1], m.scrollx[1])):
            self.mem.w16(self.sym["m72_scroll"] + 2 * k, value)
        self.mem.w16(self.sym["m72_raster"], (m.raster_line + 128) & 65535)

    def frame(self, ports, detailed=False):
        self.mem.w_block(self.sym["v30_vmarks"], bytes(0x600))
        for k, value in enumerate((ports.in0, ports.in1, ports.dsw)):
            self.mem.w16(self.sym["in_ports"] + 2 * k, value)
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["sim_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym["port_frame"])
        if not detailed:
            return self.run_to()
        cycles = 0
        while self.cpu.r_pc() != self.sym["sim_wait"]:
            pc = self.cpu.r_pc()
            if pc in self.watch:
                self.watch[pc]()
            if pc == self.sym["sim_badpc"]:
                raise RuntimeError("badpc %05X" % self.mem.r32(self.sym["badpc"]))
            count = self.cpu.execute(1).cycles
            self.prof[self.labels[bisect.bisect_right(self.addresses, pc) - 1]] += count
            cycles += count
        return cycles

    def checkpoint(self, ports, rng, state, frame):
        # Logical runtime state, addressed by symbols so relocated experiments can load it.
        names = ["ctx_main", "m72_scroll", "m72_scroll_vbl", "m72_raster", "m72_port02",
                 "m72_spritebuf", "m72_slots", "m72_objs", "m72_objs_end", "m72_slots_hw", "sound_head"]
        sizes = [64, 8, 8, 2, 2, 1024, 1024, 1024, 2, 2, 2]
        img = self.sym["v30_image"]
        return dict(frame=frame, ports=vars(ports), rng=rng.getstate(), controls=state.copy(),
                    memory={str(base): bytes(self.mem.r_block(img + base, size)) for _, base, size in REGIONS},
                    symbols={name: bytes(self.mem.r_block(self.sym[name], size)) for name, size in zip(names, sizes)})

    def load(self, checkpoint):
        img = self.sym["v30_image"]
        for base, data in checkpoint["memory"].items():
            self.mem.w_block(img + int(base), data)
        values = checkpoint["symbols"]
        ctx = bytearray(values["ctx_main"])
        old_img = int.from_bytes(ctx[48:52], "big") - (int.from_bytes(ctx[6:8], "big") << 4)
        for off in (44, 48, 52, 56):
            value = int.from_bytes(ctx[off:off + 4], "big") + img - old_img
            ctx[off:off + 4] = value.to_bytes(4, "big")
        for name, data in values.items():
            self.mem.w_block(self.sym[name], bytes(ctx) if name == "ctx_main" else data)
        # Native terrain caches derive solely from these scroll values. Force the
        # same first-use work in both relocated builds.
        for key, off in (("tc_kf", 0x42EC0), ("tc_kbx", 0x42EC8), ("tc_kby", 0x42ECC)):
            self.mem.w32(self.sym[key], self.mem.r32(img + off) ^ 0xFFFFFFFF)
        self.prof.clear()
        self.frames.clear()

    def logical_state(self):
        img = self.sym["v30_image"]
        out = {name: bytes(self.mem.r_block(img + base, size)) for name, base, size in REGIONS}
        for name, size in (("ctx_main", 64), ("m72_spritebuf", 1024), ("m72_slots", 1024),
                           ("m72_objs", 1024), ("m72_objs_end", 2), ("m72_slots_hw", 2),
                           ("m72_scroll", 8), ("m72_scroll_vbl", 8), ("m72_raster", 2),
                           ("m72_port02", 2), ("sound_head", 2)):
            out[name] = bytes(self.mem.r_block(self.sym[name], size))
        ctx = bytearray(out["ctx_main"])
        for off in (44, 48, 52, 56):
            value = int.from_bytes(ctx[off:off + 4], "big") - img
            ctx[off:off + 4] = value.to_bytes(4, "big")
        # No arithmetic flags are live at this build's idle point (gen_info).
        ctx[61] &= 0xE0
        out["ctx_main"] = bytes(ctx)
        out["v30_vmarks"] = bytes(self.mem.r_block(self.sym["v30_vmarks"], 0x600))
        out["sound_cmds"] = bytes(self.mem.r_block(self.sym["sound_cmds"], 64))
        return out


def scan(seed, starts, frames):
    h = Logic()
    _, board = snapshot.capture()
    h.initialize(board)
    ports = type("Ports", (), {})()
    ports.in0 = ports.in1 = 65535
    ports.dsw = board.dsw & ~0x4000 if seed >= 8 else board.dsw
    rng, controls = random.Random(seed), dict(hold=0, bits=0)
    results = {}
    starts = set(starts)
    for f in range(max(starts) + frames):
        if f in starts:
            packed = h.checkpoint(ports, rng, controls, f)
            (BUILD / ("seed%d_frame%d.pkl.gz" % (seed, f))).write_bytes(gzip.compress(pickle.dumps(packed), mtime=0))
            h.prof.clear()
            h.frames.clear()
        cover.press(ports, f, seed, rng, controls)
        active = any(start <= f < start + frames for start in starts)
        cycles = h.frame(ports, active)
        if active:
            h.frames.append(cycles)
        if f - frames + 1 in starts:
            start = f - frames + 1
            results[start] = dict(mean=sum(h.frames) / frames, cycles=dict(h.prof), frames=frames)
            (BUILD / ("profile_seed%d_frame%d.json" % (seed, start))).write_text(json.dumps(results[start], indent=2) + "\n")
            print("seed %d at %d: %.0f cycles; %s" % (seed, start, results[start]["mean"], h.prof.most_common(6)), flush=True)
        if f % 10000 == 0:
            print("advanced", f, flush=True)


def compare(variant, seed, starts, frames):
    # machine68k shares native emulator state between instances. Never coexist
    # two builds in one process: save a baseline oracle, then run the candidate.
    for kind in ("base", variant):
        subprocess.run([sys.executable, str(Path(__file__)), "--benchmark", kind, "--seed", str(seed),
                        "--starts", ",".join(map(str, starts)), "--frames", str(frames)], check=True)


def benchmark(variant, seed, starts, frames):
    h = Logic(variant)
    oracle_path = BUILD / ("oracle_seed%d.pkl.gz" % seed)
    oracle = {} if variant == "base" else pickle.loads(gzip.decompress(oracle_path.read_bytes()))
    reports = {}
    for start in starts:
        if variant != "base":
            assert start in oracle and len(oracle[start]["cycles"]) == frames, "create a matching baseline oracle first"
        checkpoint = pickle.loads(gzip.decompress((BUILD / ("seed%d_frame%d.pkl.gz" % (seed, start))).read_bytes()))
        h.load(checkpoint)
        ports = type("Ports", (), {})()
        ports.__dict__.update(checkpoint["ports"])
        rng, controls = random.Random(), checkpoint["controls"].copy()
        rng.setstate(checkpoint["rng"])
        cycles, hashes = [], []
        for f in range(start, start + frames):
            cover.press(ports, f, seed, rng, controls)
            cycles.append(h.frame(ports, True))
            state_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in h.logical_state().items()}
            hashes.append(state_hashes)
            if variant != "base":
                expected = oracle[start]["hashes"][f - start]
                bad = [name for name in expected if expected[name] != state_hashes[name]]
                if bad:
                    raise RuntimeError("difference at %d: %s" % (f, bad))
        if variant == "base":
            oracle[start] = dict(hashes=hashes, cycles=cycles, profile=dict(h.prof))
            oracle_path.write_bytes(gzip.compress(pickle.dumps(oracle), mtime=0))
            print("baseline", start, sum(cycles) / frames, flush=True)
        else:
            before = oracle[start]["cycles"]
            reports[start] = dict(frames=frames, before=sum(before) / frames, after=sum(cycles) / frames,
                                  change=100 * (sum(cycles) / sum(before) - 1),
                                  baseline_profile=oracle[start]["profile"], prototype_profile=dict(h.prof))
            print(start, reports[start]["before"], reports[start]["after"], reports[start]["change"], "exact", flush=True)
            (BUILD / (variant + "_seed%d_comparison.json" % seed)).write_text(json.dumps(reports, indent=2) + "\n")


def reference(variant, seed, frames, start=0, record="", windows=""):
    import logic_test
    prg, mp = build(variant)
    root = BUILD / (variant + "_reference")
    run, assets = root / "run/rtype_sim", root / "build/rtype"
    run.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    for target, source in ((run / "RTYPE.PRG", prg), (assets / "rtype_sim.map", mp),
                           (assets / "gen_info.json", ROOT / "build/rtype/gen_info.json")):
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)
    logic_test.ROOT = root
    logic_test.build_dir = lambda game: assets
    sys.argv = ["logic_test.py", str(frames), "--seed", str(seed), "--snap", "--list", "--start", str(start)]
    if record:
        sys.argv += ["--record", record]
    if windows:
        sys.argv += ["--windows", windows]
    status = logic_test.main()
    if status:
        raise SystemExit(status)


def focused(variant):
    h = Logic(variant)
    img, mem = h.sym["v30_image"], h.mem
    invalid = 0
    for target in range(256):
        for channel in range(3):
            for pen in range(16):
                cached = mem.r16(h.sym["fade_tab"] + target * 96 + channel * 32 + pen * 2)
                raw = mem.r8(img + 0x3B000 + ((target * 48 + pen * 3 + channel) ^ 1))
                invalid += cached != raw
                if variant != "base":
                    assert cached == raw, (target, channel, pen, cached, raw)
    rng = random.Random(7240)
    results = []
    cases = [("R0EC73", "R0EC81", 0xD0000, 0x200, 0xF80, 0),
             ("R0EC90", "R0EC9E", 0xD0000, 0, 0x1000, 0),
             ("R0ECAD", "R0ECBB", 0xD8000, 0, 0x1000, 0)]
    # Guard failures execute the original word loop: short fills and nonzero attributes.
    cases += [(a, b, bank, 0x100, 7, 0x1234) for a, b, bank, _, _, _ in cases]
    for entry, stop, bank, start, cells, attribute in cases:
        initial = bytes(rng.randrange(256) for _ in range(0x4000))
        mem.w_block(img + bank, initial)
        mem.w_block(h.sym["v30_vmarks"], bytes(0x600))
        want = bytearray(initial)
        for n in range(cells):
            want[start + 4 * n:start + 4 * n + 4] = (0x0FA00000 | attribute).to_bytes(4, "big")
        for reg, value in ((R.D0, attribute), (R.D1, cells), (R.D5, start), (R.A2, img + bank)):
            h.cpu.w_reg(reg, value)
        h.cpu.w_pc(h.sym[entry])
        cycles = 0
        while h.cpu.r_pc() != h.sym[stop]:
            cycles += h.cpu.execute(1).cycles
        assert bytes(mem.r_block(img + bank, 0x4000)) == want
        assert h.cpu.r_reg(R.D0) == attribute and h.cpu.r_reg(R.D1) == 0
        assert h.cpu.r_reg(R.D5) == start + 4 * cells
        marks = bytearray(0x600)
        first, last = ((bank - 0xC8000 + v) >> 6 for v in (start, start + 4 * cells - 1))
        marks[first:last + 1] = bytes([255]) * (last - first + 1)
        assert bytes(mem.r_block(h.sym["v30_vmarks"], 0x600)) == marks
        results.append(dict(entry=entry, cells=cells, attribute=attribute, cycles=cycles))
    (BUILD / ("focused_" + variant + ".json")).write_text(json.dumps(dict(palette_words=12288, invalid_palette_words=invalid, cases=results), indent=2) + "\n")
    print("focused", variant, results, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--starts", default="3000,11000,22000,33000,46500,56000,65000,74000")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--compare", choices=["fade", "fade_cache", "object", "clear", "combined", "production"])
    ap.add_argument("--benchmark", choices=["base", "fade", "fade_cache", "object", "clear", "combined", "production"])
    ap.add_argument("--reference", choices=["fade_cache", "combined", "production"])
    ap.add_argument("--start", type=int, default=0, help="reference-only frames before the comparison")
    ap.add_argument("--record", default="", help="save compared reference video states for stage_test.py")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    starts = [int(x) for x in args.starts.split(",")]
    if args.frames < 1 or min(starts) < 0:
        ap.error("invalid frame range")
    if (args.start or args.record) and not args.reference:
        ap.error("--start and --record require --reference")
    if args.reference and not 0 <= args.start < args.frames:
        ap.error("--start must be within the reference frame range")
    if args.check:
        focused(args.benchmark or "production")
    elif args.reference:
        reference(args.reference, args.seed, args.frames, args.start, args.record)
    elif args.benchmark:
        benchmark(args.benchmark, args.seed, starts, args.frames)
    elif args.compare:
        compare(args.compare, args.seed, starts, args.frames)
    else:
        scan(args.seed, starts, args.frames)
