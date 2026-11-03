"""Later-stage native experiments against the current production logic.

Private generated code, compressed checkpoints, independent worker processes.
The earlier native improvements stay enabled in both sides of the comparison.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import types

import native_audit as audit

HERE, ROOT = audit.HERE, audit.ROOT
BUILD = ROOT / "build/rtype/later_native_audit"
PRODUCTION_BUILD = audit.build
VARIANTS = ("base", "box", "script", "tiles", "terrain", "dispatch", "combined")


def check_flags():
    """Input-flag analysis with RETs terminal, independently of caller liveness."""
    import gen
    import v30x

    class TerminalEndpoints(list):
        # liveness distinguishes an unknown return from a known set of returns.
        # A known, empty set makes its third fixpoint stop at RET, like its first.
        def __bool__(self):
            return True

    prog, _, _, _ = gen.program(gen.load_regions("rtype"), gen.load_cover())
    code, _ = v30x.discover(prog)
    returns = {pc: TerminalEndpoints() for pc, ins in code.items() if ins.flow in ("ret", "retf")}
    live, _ = v30x.liveness(prog, code, returns)
    exits = (0x0F079, 0x0C86B, 0x0FA0E, 0x0F9C1, 0x02B36)
    for pc in exits:
        assert live[pc] == 0, (hex(pc), live[pc])
    assert live[0x0F97E] & v30x.C, "positive control must read carry"
    callers = {}
    for target in (0x0F978, 0x0F9C1, 0x02B36):
        sites = {hex(pc): live[v30x.next_lin(ins)] for pc, ins in code.items()
                 if ins.flow == "call" and ins.target and v30x.lin_of(*ins.target) == target}
        assert sites and all(not mask & (v30x.P | v30x.A) for mask in sites.values()), (hex(target), sites)
        callers[hex(target)] = sites
    result = dict(dead_input_exits=[hex(pc) for pc in exits], caller_return_flag_reads=callers,
                  positive_control=dict(pc="0xf97e", reads=live[0x0F97E]))
    (BUILD / "flag_checks.json").write_text(json.dumps(result, indent=2) + "\n")
    print("flag checks pass:", len(exits), "dead-input exits;", sum(map(len, callers.values())),
          "leaf callers need no parity/auxiliary flags; carry-read positive control passes", flush=True)


def focused(variant):
    """Differential boundary cases, including flags at collision-test returns."""
    h = audit.Logic(variant)
    mem, cpu, img = h.mem, h.cpu, h.sym["v30_image"]
    R = audit.R
    rng = random.Random(7241)
    oracle_file = BUILD / "focused_base.json"
    oracle = [] if variant == "base" else json.loads(oracle_file.read_text())
    results = []
    cases = [("box", i) for i in range(256)] + [("terrain", i) for i in range(64)]
    cases += [("script", i) for i in range(64)]
    cases += [("run", i) for i in range(16)] + [("patch", i) for i in range(16)]
    for kind, number in cases:
        mem.w_block(img + 0x40000, rng.randbytes(0x4000))
        # Deliberately include upper bits on tile codes and counter wraparound.
        video = bytearray(rng.randbytes(0x18000))
        for n in range(0x8000, 0xC000, 4):
            video[n:n + 2] = rng.choice((0x09F6, 0xC9F6, 0x0FA0, 0)).to_bytes(2, "big")
        mem.w_block(img + 0xC8000, bytes(video))
        mem.w_block(h.sym["v30_vmarks"], bytes(0x600))
        for reg in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6):
            cpu.w_reg(reg, rng.randrange(65536))
        ctx = h.sym["ctx_main"]
        for reg, value in ((R.A2, img + 0x10000), (R.A3, img + 0x40000),
                           (R.A4, img + 0x40000), (R.A5, img + 0x43F00), (R.A6, ctx),
                           (R.D6, 0x600)):
            cpu.w_reg(reg, value)
        mem.w16(ctx, 0x1000)
        mem.w16(ctx + 4, 0x4000)
        mem.w16(ctx + 6, 0x4000)
        flags = kind in ("box", "script", "terrain")
        if kind == "box":
            cpu.w_reg(R.D3, 0x100)
            cpu.w_reg(R.D4, 0x200)
            edges = (0, 1, 0x7FFF, 0x8000, 0xFFFE, 0xFFFF)
            for off in (0x206, 0x208, 0x202, 0x204, 0x604, 0x608):
                mem.w16(img + 0x40000 + off, rng.choice(edges) if number < 128 else rng.randrange(65536))
            for off in range(0, 8, 2):
                mem.w16(img + 0x10100 + off, rng.randrange(65536))
            entry, stops = "R0F978", ("R0F9C0", "R0F993")
        elif kind == "terrain":
            mem.w16(img + 0x40604, rng.choice((0x13F, 0x140, 0x2B4, 0xFFFF)) if number < 16 else rng.randrange(0x140, 0x300))
            mem.w16(img + 0x40608, rng.randrange(65536))
            # FG scroll's high word is nonzero: catch stale upper index bits.
            mem.w32(img + 0x42EC0, rng.randrange(0x10000, 0x1000000))
            mem.w32(h.sym["tc_kf"], mem.r32(img + 0x42EC0) ^ 0xFFFFFFFF)
            entry, stops = "R02B36", ("R02BCB", "R02B35")
        elif kind == "script":
            count = (1, 2, 3, 15, 255, 0)[number % 6]
            mem.w16(img + 0x40614, 0x100)
            mem.w16(img + 0x40612, 0x2000)
            mem.w8(img + 0x40616, count)
            program = bytearray()
            if number & 1:
                program.append(0x83)
            if number >= 32 or not count:
                program.append(4)
            else:
                for step in range(count):
                    if step % 3 == 0:
                        program.append(0x80 | (step & 31))
                    program.append(rng.randrange(128) & ~4)
            for i, value in enumerate(program):
                mem.w8(img + 0x10000 + ((0x100 + i) ^ 1), value)
            mem.w16(img + 0x12002, (0, 0x4000, 0xF003)[number % 3])
            mem.w16(img + 0x12004, 0x3000 if number % 3 == 0 else 0x4000)
            mem.w16(img + 0x13000, 0x4000)
            entry, stops = "R07E97", ("R07E9A",)
        elif kind == "run":
            bank = 0xD0000 if number < 12 else 0xD8000
            cpu.w_reg(R.A2, img + bank)
            mem.w16(ctx, bank >> 4)
            cpu.w_reg(R.D3, (0, 0x3C, 0xFC, 0x3FF0)[number % 4])
            cpu.w_reg(R.D1, (1, 48, 16, 4)[number % 4])
            entry, stops = "R0F06D", ("R0F079",)
        else:
            cpu.w_reg(R.A2, img + 0xD8000)
            cpu.w_reg(R.A3, img + 0x10000)
            mem.w16(ctx, 0xD800)
            mem.w16(ctx + 6, 0x1000)
            cpu.w_reg(R.D1, 0x607)
            cpu.w_reg(R.D3, (0, 0x3C, 0xE4, 0xE8, 0x3F00)[number % 5])
            cpu.w_reg(R.D4, 0xFFDC if number >= 12 else 0x200)
            entry, stops = "R0C84A", ("R0C86B",)
        cpu.w_pc(h.sym[entry])
        host_sp = cpu.r_reg(R.A7)
        stop_addresses = {h.sym[x] for x in stops}
        cycles = 0
        for _ in range(100000):
            if cpu.r_pc() in stop_addresses:
                break
            assert cpu.r_pc() != 0x600, (kind, number, "68000 exception")
            cycles += cpu.execute(1).cycles
        else:
            raise RuntimeError((kind, number, "timeout"))
        assert cpu.r_reg(R.A7) == host_sp, (kind, number, "host stack imbalance")
        chunks = [bytes(mem.r_block(img + a, n)) for a, n in ((0x40000, 0x4000), (0xC8000, 0x18000))]
        chunks += [bytes(mem.r_block(h.sym["v30_vmarks"], 0x600))]
        state = dict(kind=kind, case=number, hash=hashlib.sha256(b"".join(chunks)).hexdigest(),
                     registers=[cpu.r_reg(r) for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6)],
                     segments=[cpu.r_reg(r) - img for r in (R.A2, R.A3, R.A4, R.A5)],
                     flags=(cpu.r_reg(R.SR) & 15) if flags else None)
        if variant != "base":
            expected = dict(oracle[len(results)])
            del expected["cycles"]
            assert state == expected, (kind, number, state, expected)
        results.append(dict(state, cycles=cycles))
    (BUILD / ("focused_" + variant + ".json")).write_text(json.dumps(results, indent=2) + "\n")
    print("focused", variant, len(results), "cases exact", flush=True)


def build(variant):
    audit.BUILD = BUILD
    prg, mp = PRODUCTION_BUILD("production")
    assets, src = prg.parent, prg.parent.with_name(prg.parent.name.replace("_assets", "_source"))
    if variant == "base":
        return prg, mp
    p = src / "natives.s"
    original = p.read_text()
    text = original
    natives, leaves = {}, {}
    if variant == "dispatch":
        # Fuse the linked-object loop's return, next link and next indirect CALL.
        # MOVEA reads the handler directly, without a separate LEA instruction.
        text += """
late_next_object:
\tmove.w (a5)+,d6
\tmove.w 28(a4,d6.l),d0
\tcmp.w #$FFFF,d0
\tbeq R00677
\tmove.w d0,d6
\tmove.w d6,-(a5)
\tmove.w (a4,d6.l),a0
\tmove.w #$026A,-(a5)
\tadd.l a0,a0
\tadd.l a0,a0
\tadd.l #main_ip_mid,a0
\tmove.l (a0),a1
\tjmp (a1)
"""
        natives[0x0066A] = "late_next_object"
    if variant in ("box", "combined"):
        body = original.split("nat_box:\n", 1)[1].split("; -----", 1)[0]
        body = body.replace("\trts", "\tNEXIT \\1,R0F9C0")
        text += "\nLATE_BOX macro\n" + body + "\tendm\nlate_box:\n\tLATE_BOX 0\n"
        text += "late_leaf_box:\n\tsubq.l #2,a5\n\tLATE_BOX 1\n"
        natives[0x0F978] = "late_box"
        leaves[0x0F978] = ("late_leaf_box", True)
    if variant in ("script", "combined"):
        body = original.split("nat_mscr:\n", 1)[1].split("; -----", 1)[0]
        body = body.replace("beq\tR0F9C1_t", "beq\t.fallback")
        old = "\ttst.b\td0\t\t\t; (the last step: the flags of the last RCL - AL's sign and zero, OV and CY clear -,\n\tbra\tR0F9EA\t\t\t; then INC [BP+14h], DBNZ, CLR1 CY, RET)"
        assert old in body
        body = body.replace(old, """\ttst.b d0
\tmove.w sr,-(sp)
\taddq.w #1,20(a1)
\tmoveq #0,d1
\tmove.w (sp)+,ccr
\taddq.l #2,a5
\trts""")
        body = body.replace("\tjmp\tR0FA0E", "\taddq.l #4,sp\n\tjmp R0FA0E")
        text += "\nlate_leaf_mscr:\n\tsubq.l #2,a5\n" + body
        text += ".fallback:\n\taddq.l #4,sp\n\tjmp R0F9C1_t\n"
        leaves[0x0F9C1] = ("late_leaf_mscr", True)
    if variant in ("tiles", "combined"):
        text += "\n" + (HERE / "later_native_tiles.s").read_text()
        natives.update({0x0F06D: "late_tile_run", 0x0C84A: "late_bg_patch"})
    if variant in ("terrain", "combined"):
        text += "\n" + (HERE / "later_native_terrain.s").read_text()
        natives[0x02B36] = "late_terrain"
        leaves[0x02B36] = ("late_leaf_terrain", True)
    p.write_text(text)
    # Regenerate dispatch and leaf calls privately, leaving canonical fixtures intact.
    module = types.ModuleType("later_native_gen")
    module.__file__ = str(HERE / "gen.py")
    exec(compile((HERE / "gen.py").read_text(), module.__file__, "exec"), module.__dict__)
    module.build_dir = lambda game: assets
    module.NATIVES.update(natives)
    module.LEAF_CALLS.update(leaves)
    for name in audit.GENERATED:
        (assets / name).unlink()
    report = module.generate()
    assert not report["unsupported"] and report["idle_flags"] == 0
    audit.toolchain.assemble_link("rtype", "rtype.s", "native_logic", str(prg),
                                  ["SIM=1", "STAGE=1", "FADE_SNAP=1"])
    return prg, mp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=VARIANTS, default="combined")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--flags", action="store_true")
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--starts", default="3000,11000,22000,33000,46500,56000,65000,74000")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--windows", default="")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "build/rtype/native_audit").glob("seed*_frame*.pkl.gz"):
        target = BUILD / p.name
        if not target.exists():
            target.symlink_to(p)
    audit.BUILD, audit.build = BUILD, build
    starts = list(map(int, args.starts.split(",")))
    if args.flags:
        check_flags()
    elif args.check:
        focused(args.variant)
    elif args.reference:
        audit.reference(args.variant, args.seed, args.frames, args.start, windows=args.windows)
    elif args.benchmark:
        audit.benchmark(args.variant, args.seed, starts, args.frames)
    else:
        for variant in ("base", args.variant):
            subprocess.run([sys.executable, str(Path(__file__)), "--benchmark", "--variant", variant,
                            "--seed", str(args.seed), "--starts", args.starts, "--frames", str(args.frames)], check=True)


if __name__ == "__main__":
    main()
