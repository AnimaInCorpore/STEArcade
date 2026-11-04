"""Isolated higher-level logic experiments; never patch the installed program.

Use --profile for handler/callee attribution, or --variant all for the combined
production comparison. The exact, script and scan variants isolate components.
Checkpoints and oracles are private. No installed program is rebuilt.
"""
import argparse
import atexit
import bisect
import collections
import gzip
import hashlib
import json
import pickle
import random
import shutil
import subprocess
import struct
import sys

import native_audit as audit
from m72board import load_regions

HERE, ROOT = audit.HERE, audit.ROOT
BUILD = ROOT / "build/rtype/logic_level_audit"
PRODUCTION_BUILD = audit.build
BASELINE_REV = "982f885"
TEMP_DIRS = set()


@atexit.register
def cleanup():
    for path in TEMP_DIRS:
        shutil.rmtree(path, ignore_errors=True)


def exact_summary(text):
    """Keep original unsigned box edges and reject using the arcade's exact test.

    This summary is still a conservative set: owner-dependent boxes can be
    included unnecessarily. Hits always fall back to the original ordered code.
    """
    a, b = text.index("\tcmp.w\td0,d3\t\t\t; (proper spans"), text.index(".rej:\n", text.index("ECOLL\tmacro"))
    body = r"""
\tlea es_boxes,a0
\tmove.w es_n,d4
\tbra .nx
.bl:
\tcmp.w (a0),d0
\tbcs.s .left
\tcmp.w 2(a0),d0
\tbcs.s .y
\tcmp.w 2(a0),d3
\tbcc.s .next
\tbra.s .y
.left:
\tcmp.w (a0),d1
\tbcs.s .next
.y:
\tcmp.w 4(a0),d2
\tbcs.s .top
\tcmp.w 6(a0),d2
\tbcs .full
\tcmp.w 6(a0),d7
\tbcs .full
\tbra.s .next
.top:
\tcmp.w 4(a0),d6
\tbcc .full
.next:
\taddq.l #8,a0
.nx:
\tdbf d4,.bl
\tbra .rej
""".replace("\\t", "\t")
    text = text[:a] + body + text[b:]
    a = text.index("\tmove.l\td0,d2\t\t\t; (L > R")
    b = text.index("\tlea\tes_boxes,a1", a)
    return text[:a] + text[b:]


def hoist_scan(text):
    """Form the query once for the 24/3-target scan; preserve ordered first hit.

    The actual final box test reconstructs AW and flags. Only the final call's
    stack residue matters: earlier calls do not change game memory.
    """
    a = text.index("COLL_SCAN macro")
    b = text.index("\n\tendm", a)
    body = r"""COLL_SCAN macro
\tmovem.l d0/d2/d3/d5/d6,-(sp)
\tlea (a2,d3.l),a0
\tmove.w 4(a4,d6.l),d0
\tmove.w 8(a4,d6.l),d2
\tmove.w d0,d1
\tadd.w 2(a0),d1
\tmove.w d0,d3
\tadd.w (a0),d3
\tmove.w d2,d7
\tadd.w 4(a0),d7
\tmove.w d2,d6
\tadd.w 6(a0),d6
\tsuba.l a1,a1
scan_k set 0
\trept \2
\tFFLAG \1+$20*scan_k
scan_k set scan_k+1
\tendr
\tmovem.l (sp)+,d0/d2/d3/d5/d6
\tmove.w a1,d4
\tbeq.s .none
\tmove.w #\4,-2(a5)
\tbsr nat_box
.none:
\tmove.w #\1+$20*\2,d4
\tmoveq #0,d1
\tmove.w #\1+$20*(\2-1),d7
\tadd.w #$20,d7
\tandi #$FE,ccr
\tjmp \3
.hit:
\tmovem.l (sp)+,d0/d2/d3/d5/d6
\tmove.w a1,d4
\tmoveq #0,d1
\tmove.w #\1+$20*\2,d1
\tsub.w d4,d1
\tlsr.w #5,d1
\tmove.w #\4,-2(a5)
\tbsr nat_box
\tjmp \3""".replace("\\t", "\t")
    # FBOX/FFLAG are also used by ECOLL; make them available before COLL_SCAN.
    m0, m1 = text.index("FBOX\tmacro"), text.index("    ifd ES_COUNT")
    macros = text[m0:m1]
    text = text[:m0] + text[m1:]
    return text[:a] + macros + body + text[b:]


def build(variant):
    audit.BUILD = BUILD
    prg, mp = PRODUCTION_BUILD("production")
    src = prg.parent.with_name(prg.parent.name.replace("_assets", "_source"))
    TEMP_DIRS.update((prg.parent, src))
    # Retain the original experiment after the later structural natives have
    # been integrated. Generated translation and replay fixtures stay shared.
    for name in ("natives.s", "core.s"):
        original = subprocess.check_output(["git", "show", BASELINE_REV + ":games/rtype/src/" + name], cwd=ROOT)
        (src / name).write_bytes(original)
    if variant == "base":
        audit.toolchain.assemble_link("rtype", "rtype.s", "native_logic", str(prg),
                                      ["SIM=1", "STAGE=1", "FADE_SNAP=1"])
        return prg, mp
    p = src / "natives.s"
    text = p.read_text()
    if variant in ("exact", "combined", "all"):
        text = exact_summary(text)
    if variant in ("scan", "all"):
        text = hoist_scan(text)
    if variant in ("script", "combined", "all"):
        # A compiled transition for two ordinary motion commands, including any
        # intervening animation bytes. End commands/wrapping/non-ROM use the
        # original interpreter. No runtime cache or invalidation is required.
        rom = load_regions("rtype")["main"][0x10000:0x20000]
        table = bytearray()
        for start in range(65536):
            pos, count, dx, dy, anim, valid, last = start, 0, 0, 0, -1, 1, 0
            while count < 2:
                if pos >= 65536:
                    valid = 0; break
                last = rom[pos]; pos += 1
                if last & 128:
                    anim = last & 31
                    continue
                if last & 4:
                    valid = 0; break
                dx += (-1 if last & 64 else 1) if last & 32 else 0
                dy += (-1 if last & 16 else 1) if last & 8 else 0
                count += 1
            al = ((last << 6) | (last >> 3)) & 255
            table += struct.pack(">HbbBBH", (pos-1)&65535, dx, dy, anim&255, al, valid)
        (prg.parent / "motion_pairs.bin").write_bytes(table)
        needle = "\tlea\t(a4,d6.l),a1\n\tmove.w\t20(a1),d3\t\t; BW = [BP+14h]"
        assert text.count(needle) == 1
        text = text.replace(needle, "\tcmp.w #2,d1\n\tbne.s motion_original\n\tcmp.l #v30_image+$10000,a2\n\tbeq motion_pair\nmotion_original:\n" + needle)
        text += r"""
\tsection text,code
motion_pair:
\tmove.w 20(a4,d6.l),d3
\tmoveq #0,d7
\tmove.w d3,d7
\tlsl.l #3,d7
\tlea motion_pairs,a0
\tadda.l d7,a0
\ttst.w 6(a0)
\tbeq motion_original
\tlea (a4,d6.l),a1
\tmove.b 2(a0),d7
\text.w d7
\tadd.w d7,4(a1)
\tmove.b 3(a0),d7
\text.w d7
\tadd.w d7,8(a1)
\tmove.b 4(a0),d7
\tbmi.s .noanim
\tmove.b d7,23(a1)
.noanim:
\tmove.w (a0),d3
\tmove.w d3,20(a1)
\tmoveq #1,d1
\tmove.b 5(a0),d0
\ttst.b d0
\tjmp R0F9EA
\tsection data,data
\teven
motion_pairs: incbin "motion_pairs.bin"
\tsection text,code
""".replace("\\t", "\t")
    p.write_text(text)
    audit.toolchain.assemble_link("rtype", "rtype.s", "native_logic", str(prg),
                                  ["SIM=1", "STAGE=1", "FADE_SNAP=1"])
    return prg, mp


class Logic(audit.Logic):
    def frame(self, ports, detailed=False):
        if not getattr(self, "semantic", False):
            return super().frame(ports, detailed)
        self.events = collections.Counter()
        self.handler_cost = collections.Counter()
        self.handler_parts = collections.defaultdict(collections.Counter)
        self.active = None
        self.elapsed = 0
        s, m, cpu = self.sym, self.mem, self.cpu
        def movement():
            bp = cpu.r_reg(audit.R.D6)
            addr = cpu.r_reg(audit.R.A4) + bp
            count = m.r8(addr + 22)
            self.events["script_steps_%d" % count] += 1
            self.events["script_segment_%x" % (cpu.r_reg(audit.R.A2) - s["v30_image"])] += 1
        def objstart():
            bp = cpu.r_reg(audit.R.D6)
            ip = m.r16(cpu.r_reg(audit.R.A4) + bp)
            self.active = ("%04x" % ip, self.elapsed)
        def objend():
            if self.active:
                ip, since = self.active
                self.handler_cost[ip] += self.elapsed - since
                self.events["handler_" + ip] += 1
                self.active = None
        self.watch = {s["nat_mscr"]: movement, s["R00667"]: objstart, s["R0066A"]: objend}
        # Profile as in audit.Logic, with cycle totals visible to semantic hooks.
        original = cpu.execute
        # Extension methods cannot be monkeypatched. Use our own stepper below.
        m.w_block(s["v30_vmarks"], bytes(0x600))
        for k, value in enumerate((ports.in0, ports.in1, ports.dsw)):
            m.w16(s["in_ports"] + 2*k, value)
        sp = cpu.r_reg(audit.R.A7) - 4
        m.w32(sp, s["sim_wait"])
        cpu.w_reg(audit.R.A7, sp)
        cpu.w_pc(s["port_frame"])
        while cpu.r_pc() != s["sim_wait"]:
            pc = cpu.r_pc()
            if pc in self.watch:
                self.watch[pc]()
            if pc == s["sim_badpc"] or pc == 0x600:
                raise RuntimeError("bad PC %x" % pc)
            count = original(1).cycles
            label = self.labels[bisect.bisect_right(self.addresses, pc)-1]
            self.prof[label] += count
            if self.active:
                self.handler_parts[self.active[0]][label] += count
            self.elapsed += count
        return self.elapsed


def profile(seed, starts, frames):
    h = Logic("base")
    h.semantic = True
    results = {}
    for start in starts:
        checkpoint = pickle.loads(gzip.decompress((BUILD / ("seed%d_frame%d.pkl.gz" % (seed,start))).read_bytes()))
        h.load(checkpoint)
        ports = type("Ports", (), checkpoint["ports"].copy())()
        rng = random.Random(); rng.setstate(checkpoint["rng"])
        controls = checkpoint["controls"].copy()
        events, handlers = collections.Counter(), collections.Counter()
        parts = collections.defaultdict(collections.Counter)
        cycles = []
        for f in range(start, start+frames):
            audit.cover.press(ports, f, seed, rng, controls)
            cycles.append(h.frame(ports, True))
            events.update(h.events); handlers.update(h.handler_cost)
            for ip, counts in h.handler_parts.items():
                parts[ip].update(counts)
        result = dict(frames=frames, mean=sum(cycles)/frames, events=dict(events),
                      handlers=dict(handlers), profile=dict(h.prof),
                      handler_profile={ip:dict(p) for ip,p in parts.items()})
        results[start] = result
        print(start, result["mean"], events.most_common(10), handlers.most_common(8), flush=True)
    (BUILD / ("semantic_seed%d.json" % seed)).write_text(json.dumps(results, indent=2)+"\n")


def capture(seed, starts):
    """Create additional checkpoints by advancing the independent reference."""
    h = Logic("base")
    board = audit.snapshot.RType()
    board.boot()
    if seed >= 8:
        board.dsw &= ~0x4000
    rng, controls = random.Random(seed), dict(hold=0, bits=0)
    for f in range(max(starts)+1):
        if f in starts:
            h.initialize(board)
            checkpoint = h.checkpoint(board, rng, controls, f)
            # Only input words, not the board's full instance dictionary.
            checkpoint["ports"] = dict(in0=board.in0,in1=board.in1,dsw=board.dsw)
            path = BUILD / ("seed%d_frame%d.pkl.gz" % (seed,f))
            if path.is_symlink():
                path.unlink()  # Never replace the original baseline fixture.
            path.write_bytes(gzip.compress(pickle.dumps(checkpoint),mtime=0))
            print("captured independent reference", seed, f, flush=True)
        if f < max(starts):
            audit.cover.press(board, f, seed, rng, controls)
            board.run_frame_port()
        if f % 5000 == 0:
            print("reference advanced", f, flush=True)


def focused(variant):
    """Differential native execution: unsigned edges, ordering, flags, fallbacks."""
    h = Logic(variant)
    m,cpu,s,R = h.mem,h.cpu,h.sym,audit.R
    img = s["v30_image"]
    rng = random.Random(7249)
    path = BUILD / "focused_base.json"
    oracle = [] if variant == "base" else json.loads(path.read_text())
    results = []
    for case in range(1152):
        m.w_block(img+0x40000,rng.randbytes(0x4000))
        for reg in (R.D0,R.D1,R.D2,R.D3,R.D4,R.D5,R.D6):
            cpu.w_reg(reg,rng.randrange(65536))
        for reg,value in ((R.A2,img+0x10000),(R.A3,img+0x40000),(R.A4,img+0x40000),
                          (R.A5,img+0x43f00),(R.A6,s["ctx_main"]),(R.D6,0x600),(R.D3,0x100)):
            cpu.w_reg(reg,value)
        cpu.w_reg(R.SR,0x2000|rng.randrange(16))
        m.w16(s["ctx_main"]+6,0x4000)
        if case < 512:
            kind = "scan24" if case < 256 else "scan3"
            edges = (0,1,0x7fff,0x8000,0xfffe,0xffff)
            for obj in [0x176+32*k for k in range(24)]+[0x4d6+32*k for k in range(3)]:
                m.w8(img+0x40000+obj, rng.choice((0,0,1,255)))
                for off in (2,4,6,8):
                    m.w16(img+0x40000+obj+off,rng.choice(edges) if case%2 else rng.randrange(65536))
            # Include no active targets, guaranteed first/last hits and duplicates.
            first,count = (0x176,24) if case < 256 else (0x4d6,3)
            if case%8 < 3:
                for k in range(count): m.w8(img+0x40000+first+32*k,0)
                if case%8:
                    obj=first+(count-1)*32 if case%8==2 else first
                    m.w8(img+0x40000+obj,1)
                    m.w_block(img+0x40000+obj+2,struct.pack('>4H',100,200,100,200))
                    m.w16(img+0x40604,150);m.w16(img+0x40608,150)
            for off in range(0,8,2): m.w16(img+0x10100+off,rng.randrange(65536))
            entry,stop=("nat_coll24","R0F977") if case<256 else ("nat_coll3","R0F95F")
            stops={s[stop]}
        elif case < 1024:
            kind="enemy_collision" if case<768 else "tough_collision"
            m.w_block(img+0x40000,bytes(0x4000))
            edges=(0,1,0x100,0x2b3,0x2b4,0x7fff,0x8000,0xfffe,0xffff)
            for obj in [0x56,0x76,0x136,0x156,0xf6,0x116,0xa8,0xc8,0xb6,0xd6]+[0x176+32*k for k in range(24)]+[0x4d6+32*k for k in range(3)]:
                m.w8(img+0x40000+obj,rng.choice((0,0,1)))
                for off in (2,4,6,8):
                    m.w16(img+0x40000+obj+off,rng.choice(edges) if case%2 else rng.randrange(65536))
            m.w16(img+0x40604,rng.choice(edges))
            m.w16(img+0x40608,rng.choice(edges))
            cpu.w_reg(R.D5,rng.randrange(0,65528,2))
            m.w8(s["es_ok"],0)
            m.w16(img+0x43efe,0x026a)
            host_sp=cpu.r_reg(R.A7)
            m.w32(host_sp-4,s["sim_wait"])
            cpu.w_reg(R.A7,host_sp-4)
            entry="leaf_ecoll" if case<768 else "leaf_eco2"
            stops={s["sim_wait"],s["R0066A"]}
        else:
            kind="script"
            # ROM remains immutable: cover normal, animation, terminal, end and
            # count/segment guard cases using its actual bytes.
            count=(2,2,2,1,3,0)[case%6]
            pos=(0xffff,0xfffe,0,0x100)[case%4] if case<1040 else rng.randrange(65536)
            m.w16(img+0x40614,pos)
            m.w8(img+0x40616,count)
            entry="nat_mscr"
            stops={s[k] for k in ("R0F9EA","R0FA0E","R0F9C1_t")}
            if case%7==0:
                cpu.w_reg(R.A2,img+0x20000)
        cpu.w_pc(s[entry])
        if not 512<=case<1024:
            host_sp=cpu.r_reg(R.A7)
        cycles=0
        for _ in range(200000):
            if cpu.r_pc() in stops: break
            assert cpu.r_pc()!=0x600,(kind,case,"exception")
            cycles+=cpu.execute(1).cycles
        else: raise RuntimeError((kind,case,"timeout"))
        assert cpu.r_reg(R.A7)==host_sp,(kind,case,"host stack")
        state=dict(kind=kind,case=case,
                   ram=hashlib.sha256(bytes(m.r_block(img+0x40000,0x4000))).hexdigest(),
                   registers=[cpu.r_reg(r) for r in (R.D0,R.D1,R.D2,R.D3,R.D4,R.D5,R.D6)],
                   segments=[cpu.r_reg(r)-img for r in (R.A2,R.A3,R.A4,R.A5)],
                   flags=cpu.r_reg(R.SR)&15)
        if variant!="base":
            expected=dict(oracle[case]);expected.pop("cycles")
            assert state==expected,(kind,case,state,expected)
        results.append(dict(state,cycles=cycles))
    (BUILD/("focused_"+variant+".json")).write_text(json.dumps(results,indent=2)+"\n")
    print("focused",variant,len(results),"cases exact",flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=("base", "exact", "script", "combined", "scan", "all"), default="exact")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--focused", action="store_true")
    ap.add_argument("--benchmark", action="store_true")
    ap.add_argument("--reference", action="store_true")
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--starts", default="22000,65000")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--windows", default="")
    args = ap.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "build/rtype/native_audit").glob("seed*_frame*.pkl.gz"):
        dest = BUILD / p.name
        if not dest.exists(): dest.symlink_to(p)
    audit.BUILD, audit.build, audit.Logic = BUILD, build, Logic
    starts = list(map(int, args.starts.split(",")))
    if args.focused:
        focused(args.variant)
    elif args.capture:
        capture(args.seed, starts)
    elif args.profile:
        profile(args.seed, starts, args.frames)
    elif args.reference:
        try:
            audit.reference(args.variant, args.seed, args.frames, windows=args.windows)
        finally:
            shutil.rmtree(BUILD/(args.variant+"_reference"),ignore_errors=True)
    elif args.benchmark:
        audit.benchmark(args.variant, args.seed, starts, args.frames)
    else:
        for variant in ("base", args.variant):
            subprocess.run([sys.executable, __file__, "--benchmark", "--variant", variant,
                            "--seed", str(args.seed), "--starts", args.starts, "--frames", str(args.frames)], check=True)


if __name__ == "__main__":
    main()
