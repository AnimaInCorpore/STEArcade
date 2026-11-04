"""Measure structural changes inside existing natives in isolated STE programs.

Production source, generated code, installed PRG and replay fixtures are read
only. CPU timings include guards and preparation, and exclude the renderer.
"""
import argparse
import atexit
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

import native_audit as audit
import logic_level_audit as level

HERE, ROOT = audit.HERE, audit.ROOT
BUILD = ROOT / "build/rtype/native_structure_audit"
BASELINE_REV = "982f885"
TEMPS = []
VARIANTS = ("base", "emit", "return_aw", "append", "tiles", "pc_tiles", "posadd", "fade_pairs", "move_flags", "dma", "combined", "best")


@atexit.register
def cleanup():
    for path in TEMPS:
        shutil.rmtree(path, ignore_errors=True)


def emit(text):
    """Specialize the dominant one-entry record; avoid generic tail loops/spills."""
    a = text.index("EMIT1_BODY macro")
    b = text.index("\n\tendm", a)
    original = text[a:b].split("\n", 1)[1]
    body = r"""EMIT1_BODY macro
    ifd SPRITE_LIST
\tmove.w $2EFC(a3),d4
\tmove.w d4,d5
\tmoveq #8,d0
\tbtst #6,4(a2,d3.l)
\tbeq.s .size\@
\tmoveq #16,d0
.size\@:
\tadd.w d5,d0
\tcmp.w #$3C8,d0
\tbcc .exit\@
\tmove.w d0,$2EFC(a3)
\tlea (a4,d6.l),a1
\tmove.w 4(a1),d1
\tmove.w 8(a1),d2
\tmove.w 6(a6),\1(a5)
\tmove.w 4(a2,d3.l),d0
\tmoveq #6,d7
\tadd.w d6,d7
\teor.w #1,d7
\tmove.b (a4,d7.l),d0
\tlea m72_slots,a0
\tadda.l d4,a0
\tmove.w d3,(a0)+
\tmove.b #1,(a0)+
\tmove.b d0,(a0)+
\tmove.w d1,(a0)+
\tmove.w d2,(a0)+
\tbtst #14,d0
\tbeq.s .exit\@
\tclr.w (a0)
.exit\@:
    else
""".replace("\\t", "\t") + original + "\n    endc"
    return text[:a] + body + text[b:]


def return_aw(text):
    """Reuse the query endpoints to form AW on the common rejection exit.

    Owner-dependent last-box selection destroys those values, so that path
    retains the original nat_box call. Return flags are set by the common tail.
    """
    needle = "\tmove.w\tes_lastip,d7\n\tbra\t.rend"
    assert text.count(needle) == 1
    body = r"""\tmove.w es_lastip,d7
    ifd ES_CHECK
\tbra .rend
    else
    if \2=0
\tcmp.w 2(a3,d4.w),d0
\tbcs.s .awl\@
\tcmp.w 4(a3,d4.w),d0
\tbcs.s .awy\@
\tmove.w d3,d0
\tcmp.w 4(a3,d4.w),d0
\tbcc.s .awdone\@
\tbra.s .awy\@
.awl\@:
\tmove.w d1,d0
\tcmp.w 2(a3,d4.w),d0
\tbcs.s .awdone\@
.awy\@:
\tmove.w d2,d0
\tcmp.w 6(a3,d4.w),d0
\tbcs.s .awtop\@
\tcmp.w 8(a3,d4.w),d0
\tbcs.s .awdone\@
\tadd.w 4(a2,d5.l),d0
\tbra.s .awdone\@
.awtop\@:
\tmove.w d6,d0
.awdone\@:
\tmovem.l (sp)+,d2/d6
\tmove.w d5,d3
\tmove.w a1,d4
\tbra .r
    else
\tbra .rend
    endc
    endc""".replace("\\t", "\t")
    return text.replace(needle, body)


def append(text):
    """An undeduplicated conservative list: cheaper builds, more query work."""
    a = text.index(".o2:\tlea\tes_boxes,a1")
    b = text.index("\tmove.l\td0,(a1)+", a)
    body = """.o2:\tlea es_boxes,a1
\tmove.w es_n,d2
\tlsl.w #3,d2
\tadda.w d2,a1
"""
    return text[:a] + body + text[b:]


def tiles(text):
    """Share the object's address between FG/BG and bypass clamped row work."""
    a,b = text.index("FG_AT\tmacro"),text.index("nat_fgtile:")
    body = text[a:b]
    body = body.replace("\tmove.l\t$2EC0(a3),d7", "\tlea (a4,d6.l),a1\n\tmove.l\t$2EC0(a3),d7",1)
    for old,new in (("4(a4,d6.l)","4(a1)"),("8(a4,d6.l)","8(a1)")):
        body=body.replace(old,new)
    body=body.replace("\tbcc.s\t.y\\@\n\tmoveq\t#0,d0\n.y\\@:","\tbcs.s .rowdone\\@\n")
    body=body.replace("\tadd.w\td0,d3\n\tand.w\t#$3FFF,d3", "\tadd.w\td0,d3\n.rowdone\\@:\n\tand.w\t#$3FFF,d3",1)
    body=body.replace("\tbcc.s\t.by\\@\n\tmoveq\t#0,d7\n.by\\@:","\tbcs.s .bgrowdone\\@\n")
    body=body.replace("\tadd.w\td7,d5\t\t\t; IY\n\tand.w", "\tadd.w\td7,d5\t\t\t; IY\n.bgrowdone\\@:\n\tand.w",1)
    return text[:a]+body+text[b:]


def pc_tiles(text):
    """Keep writable derived fields near the routines using PC-relative reads."""
    needle="\tsection data,data\ntc_kf:"
    assert text.count(needle)==1
    text=text.replace(needle,"\tsection text,code\ntc_kf:")
    a,b=text.index("FG_AT\tmacro"),text.index("nat_fgtile:")
    body=text[a:b]
    body=re.sub(r"\b(tc_(?:kf|kbx|kby|cxf|cwf|basef|cxb|basebx|byterm|yb))(?=,)",r"\1(pc)",body)
    return text[:a]+body+text[b:]


def posadd(text):
    """Use the 68000 X flag across MOVE/EXT to add discontiguous 24-bit fields.

    This is restricted to inline updates in the bullet and decorative-object
    handlers: AW is overwritten before use afterwards. General position
    routines still keep AW.
    """
    a=text.index("POSADD\tmacro")
    b=text.index("\n\tendm",a)
    body=r"""POSADD macro
\tmove.b \1-2(a0),d7
\tadd.b d0,d7
\tmove.b d7,\1-2(a0)
\tmove.b \2(a0),d0
\text.w d0
\tmove.w \1(a0),d7
\taddx.w d0,d7
\tmove.w d7,\1(a0)""".replace("\\t","\t")
    text=text[:a]+body+text[b:]
    for offset,source in ((4,"$30"),(8,"$32")):
        pattern=r"(?m)^([ \t]*POSADD[ \t]+)"+str(offset)+r"[ \t]*$"
        text=re.sub(pattern,lambda match:match[1]+str(offset)+","+source,text)
    return text


def fade_pairs(text):
    """Use cached word targets and pair comparisons on the changed-row path."""
    needle=".slow\\@:\tlea\t(a3,d3.l),a0\n\tmoveq\t#0,d2"
    assert text.count(needle)==1
    body=""".slow\\@:
\tlea (a3,d3.l),a0
\tcmp.l #v30_image+$3B000,a2
\tbne .bytes\\@
\tmoveq #0,d2
\tmove.w d4,d2
\tadd.l d2,d2
\tlea fade_tab,a1
\tadda.l d2,a1
\tmove.w 94(a1),d0
\tsub.w $41E(a0),d0
\tmove.w d0,-(sp)
\tmoveq #0,d2
"""
    for k in range(24):
        suffix="\\@_"+str(k)
        body+=f"""\tmove.l (a1)+,d7
\tcmp.l (a0),d7
\tbeq.s .pair_next{suffix}
\tmove.l d7,d0
\tswap d0
\tcmp.w (a0),d0
\tbeq.s .pair_low{suffix}
\taddq.w #1,d2
.pair_low{suffix}:
\tcmp.w 2(a0),d7
\tbeq.s .pair_store{suffix}
\taddq.w #1,d2
.pair_store{suffix}:
\tmove.l d7,(a0)
.pair_next{suffix}:
\taddq.l #4,a0
"""
        if k in (7,15):body+="\tlea $200-32(a0),a0\n"
    body+="""\tmoveq #0,d0
\tmove.w (sp)+,d0
\tadd.w #48,d4
\tbra .tail\\@
.bytes\\@:
\tmoveq #0,d2"""
    return text.replace(needle,body)


def dma(text):
    """Copy a variable number of records with one dispatch, no per-record DBF."""
    text=text.replace("\tbls.s\t.none", "\tbls\t.none",1)
    a=text.index("\tlsr.w\t#3,d0",text.index("m72_sprite_dma:"))
    b=text.index(".none:",a)
    body=r"""\tlsr.w #3,d0
\tcmp.w #96,d0
\tbhi .original
\tlea m72_slots+$C0,a0
\tlea m72_objs+$C0,a1
\tneg.w d0
\tadd.w #96,d0
\tlsl.w #2,d0
\tjmp .copies(pc,d0.w)
.copies:
\trept 96
\tmove.l (a0)+,(a1)+
\tmove.l (a0)+,(a1)+
\tendr
\tbra .none
.original:
\tsubq.w #1,d0
\tlea m72_slots+$C0,a0
\tlea m72_objs+$C0,a1
.c:
\tmove.l (a0)+,(a1)+
\tmove.l (a0)+,(a1)+
\tdbf d0,.c
""".replace("\\t", "\t")
    # The fixed slots are always exactly 64 bytes.
    text=text[:a]+body+text[b:]
    a=text.index("\tmoveq\t#$40/4-1,d0",text.index("m72_sprite_dma:"))
    b=text.index("\tmovem.l\t(sp)+,d0/a0-a1",a)
    return text[:a]+"\trept 16\n\tmove.l (a0)+,(a1)+\n\tendr\n"+text[b:]


def move_flags(text):
    # MOVEQ #0,D1 already supplies exactly CMP.B D0,D0's N/Z/V/C,
    # and both leave X alone. No extra flag instruction is needed.
    needle="\tmoveq\t#0,d1\n\tcmp.b\td0,d0"
    assert text.count(needle)==1
    text=text.replace(needle,"\tmoveq\t#0,d1")
    # Keep the count comparison before the final OR.B that establishes the
    # script result flags, removing the subsequent TST.B restoration.
    a=text.index("nat_mscr:")
    b=text.index("; -----",a)
    old="""\tlsl.b\t#6,d0
\tor.b\td7,d0
\tcmp.w\t#1,d1
\tbne.s\t.more
\ttst.b\td0\t\t\t; (the last step: the flags of the last RCL - AL's sign and zero, OV and CY clear -,
\tbra\tR0F9EA\t\t\t; then INC [BP+14h], DBNZ, CLR1 CY, RET)
.more:\taddq.w\t#1,20(a1)"""
    new="""\tcmp.w #1,d1
\tbne.s .more
\tlsl.b #6,d0
\tor.b d7,d0
\tbra R0F9EA
.more:
\tlsl.b #6,d0
\tor.b d7,d0
\taddq.w #1,20(a1)"""
    body=text[a:b]
    assert body.count(old)==1
    return text[:a]+body.replace(old,new)+text[b:]


def build(variant):
    work=BUILD/(variant+"_"+str(os.getpid()))
    assets,src=work/"assets",work/"src"
    assets.mkdir(parents=True,exist_ok=True);src.mkdir(exist_ok=True)
    TEMPS.append(work)
    for p in (ROOT/"build/rtype").iterdir():
        if p.is_file(): (assets/p.name).symlink_to(p)
    for p in (HERE.parent/"src").glob("*.s"): shutil.copy2(p,src/p.name)
    for name in ("natives.s","core.s"):
        original=subprocess.check_output(["git","show",BASELINE_REV+":games/rtype/src/"+name],cwd=ROOT)
        (src/name).write_bytes(original)
    text=(src/"natives.s").read_text()
    selected={"emit","return_aw","append","tiles","dma"} if variant=="combined" else {variant}
    if variant=="best":selected={"emit","return_aw","pc_tiles","posadd","fade_pairs","move_flags","dma"}
    for name,patch in (("emit",emit),("return_aw",return_aw),("append",append),("tiles",tiles),("pc_tiles",pc_tiles),("posadd",posadd),("fade_pairs",fade_pairs),("move_flags",move_flags)):
        if name in selected:text=patch(text)
    (src/"natives.s").write_text(text)
    if "dma" in selected:
        p=src/"core.s";p.write_text(dma(p.read_text()))
    audit.toolchain.src_dir=lambda game:src
    audit.toolchain.build_dir=lambda game:assets
    prg=assets/"RTYPE.PRG"
    audit.toolchain.assemble_link("rtype","rtype.s","native_logic",str(prg),["SIM=1","STAGE=1","FADE_SNAP=1"])
    return prg,assets/"native_logic.map"


def extra(variant):
    """Actual native entry/exit checks for emitter, terrain and non-SIM DMA."""
    h=audit.Logic(variant)
    m,cpu,s,R=h.mem,h.cpu,h.sym,audit.R
    img=s["v30_image"]
    path=BUILD/"extra_base.json"
    oracle=[] if variant=="base" else json.loads(path.read_text())
    rng=random.Random(7250);results=[]
    for case in range(1024):
        m.w_block(img+0x40000,rng.randbytes(0x4000))
        m.w_block(s["m72_slots"],rng.randbytes(1024))
        for reg in (R.D0,R.D1,R.D2,R.D3,R.D4,R.D5,R.D6):cpu.w_reg(reg,rng.randrange(65536))
        for reg,value in ((R.A2,img+0x10000),(R.A3,img+0x40000),
                          (R.A4,img+(0x41000 if case%3==0 else 0x40000)),
                          (R.A5,img+0x43f00),(R.A6,s["ctx_main"]),(R.D6,0x600),
                          (R.D3,0x100)):
            cpu.w_reg(reg,value)
        cpu.w_reg(R.SR,0x2000|rng.randrange(16))
        m.w16(s["ctx_main"]+6,0x4000)
        if case<256:
            kind="emit1"
            attr=rng.randrange(65536)
            m.w16(img+0x10104,attr)
            slot=(0xc0,0xc8,0x3a8,0x3b0,0x3b8,0x3c0,0x3c8,0x3d0)[case%8]
            m.w16(img+0x42efc,slot)
            entry,stop="nat_emit1","R0201A"
        elif case<512:
            kind="fgtile" if case<384 else "bgtile"
            # Repeated keys exercise cache hits as well as invalidation.
            if case%4:
                for off in (0x42ec0,0x42ec8,0x42ecc):m.w32(img+off,rng.randrange(2**32))
            obj=cpu.r_reg(R.A4)+0x600
            m.w16(obj+4,rng.choice((0,1,0x13f,0x140,0x2b4,0x8000,0xffff)))
            m.w16(obj+8,(0,0x17e,0x17f,0x180,0x186,0x187,0x8000,0xffff)[case%8])
            for off in (0xd0000,0xd8000):m.w_block(img+off,rng.randbytes(0x4000))
            entry,stop=("nat_fgtile","R022B4") if case<384 else ("nat_bgtile","R0231A")
        elif case<768:
            kind="bullet_posadd" if case<640 else "decorative_posadd"
            obj=cpu.r_reg(R.A4)+0x600
            m.w16(obj,0xe603)
            m.w16(img+0x42efc,0xc0)
            values=(0,1,0x7f,0x80,0xff,0x100,0x7fff,0x8000,0xff7f,0xff80,0xfffe,0xffff)
            for off in (4,8,0x30,0x32):m.w16(obj+off,rng.choice(values))
            for off in (2,6):m.w8(obj+off,rng.choice((0,1,0x7f,0x80,0xfe,0xff)))
            m.w16(img+0x42eb6,case&1)
            m.w8(img+0x40056,case&1)
            m.w_block(img+0x40058,bytes(8))
            m.w_block(img+0x40078,bytes(8))
            if case<640:
                entry="nat_he601"
                stops={s[n] for n in ("R0EA4A","R0EA86","R0EA7B","R0EA7C")}
            else:
                m.w16(obj+0x34,0x84ae)
                m.w8(img+0x42fc5,case%7==0)
                entry="nat_nh_e5cd"
                stops={s[n] for n in ("R0E9E0","R0E9F7","R0E9CD_t")}
        else:
            kind="fade_pairs"
            cpu.w_reg(R.A2,img+(0x20000 if case%11==0 else 0x3b000))
            target=rng.randrange(256)
            start=0x2134+(case%16)*32
            cpu.w_reg(R.D3,start);cpu.w_reg(R.D4,target*48)
            for plane in range(3):
                for pen in range(16):
                    value=m.r16(s["fade_tab"]+target*96+32*plane+2*pen)
                    if case%4==0 or (case%4==1 and pen==15 and plane==2) or (case%4==2 and pen%2):
                        value=(value+1+case)%65536
                    m.w16(img+0x40000+start+0x200*plane+2*pen,value)
            entry,stop="nat_fade_a","R057B4"
        if kind not in ("bullet_posadd","decorative_posadd"):stops={s[stop]}
        cpu.w_pc(s[entry]);host_sp=cpu.r_reg(R.A7);cycles=0
        for _ in range(10000):
            if cpu.r_pc() in stops:break
            assert cpu.r_pc()!=0x600,(kind,case,"exception")
            cycles+=cpu.execute(1).cycles
        else:raise RuntimeError((kind,case,"timeout"))
        assert cpu.r_reg(R.A7)==host_sp,(kind,case,"host stack")
        chunks=[bytes(m.r_block(img+0x40000,0x4000)),bytes(m.r_block(s["m72_slots"],1024))]
        state=dict(kind=kind,case=case,memory=hashlib.sha256(b''.join(chunks)).hexdigest(),
                   registers=[cpu.r_reg(r) for r in (R.D0,R.D1,R.D2,R.D3,R.D4,R.D5,R.D6)],
                   segments=[cpu.r_reg(r)-img for r in (R.A2,R.A3,R.A4,R.A5)],
                   flags=cpu.r_reg(R.SR)&15 if 256<=case<640 else None)
        if variant!="base":
            expected=dict(oracle[case]);expected.pop("cycles")
            assert state==expected,(kind,case,state,expected)
        results.append(dict(state,cycles=cycles))
    (BUILD/("extra_"+variant+".json")).write_text(json.dumps(results,indent=2)+"\n")
    print("extra",variant,len(results),"cases exact",flush=True)
    import dma_test
    costs=[]
    source=(HERE.parent/"src/core.s").read_text()
    if variant in ("dma","combined","best"):source=dma(source)
    count=sum(dma_test.check(source,n,costs) for n in (3,0))
    (BUILD/("dma_"+variant+".json")).write_text(json.dumps(costs,indent=2)+"\n")
    print("DMA",variant,count,"non-SIM cases pass",flush=True)


def main():
    global BUILD
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant",choices=VARIANTS,default="combined")
    ap.add_argument("--benchmark",action="store_true")
    ap.add_argument("--focused",action="store_true")
    ap.add_argument("--extra",action="store_true")
    ap.add_argument("--dump",action="store_true",help="save the first resulting state for diagnosis")
    ap.add_argument("--hatari",action="store_true")
    ap.add_argument("--reference",action="store_true")
    ap.add_argument("--windows",default="")
    ap.add_argument("--series",default="",help="separate result/oracle set, e.g. quick120")
    ap.add_argument("--seed",type=int,default=10)
    ap.add_argument("--starts",default="22000,65000")
    ap.add_argument("--frames",type=int,default=120)
    args=ap.parse_args()
    if args.series:
        if not re.fullmatch(r"[a-z0-9_-]+",args.series):ap.error("invalid series name")
        BUILD=BUILD/args.series
    BUILD.mkdir(parents=True,exist_ok=True)
    for origin in (ROOT/"build/rtype/native_audit",ROOT/"build/rtype/logic_level_audit"):
        for p in origin.glob("seed*_frame*.pkl.gz"):
            dest=BUILD/p.name
            if not dest.exists():dest.symlink_to(p.resolve())
    audit.BUILD,audit.build=BUILD,build
    if args.hatari:
        import native_hatari as hw
        start=int(args.starts.split(",")[0])
        hw.ROOT=BUILD/"hardware"
        hw.BUILD=BUILD/("hatari_%d_%d"%(args.seed,start))
        hw.build=lambda variant:build("base" if variant=="base" else "best")
        sys.argv=["native_hatari.py","--candidate","combined","--seed",str(args.seed),
                  "--start",str(start),"--frames",str(args.frames),"--checkpoint",
                  str(BUILD/("seed%d_frame%d.pkl.gz"%(args.seed,start)))]
        hw.main()
    elif args.reference:
        import logic_test
        prg,mp=build(args.variant)
        root=BUILD/("reference_%d_%d"%(args.seed,os.getpid()))
        TEMPS.append(root)
        run,assets=root/"run/rtype_sim",root/"build/rtype"
        run.mkdir(parents=True,exist_ok=True);assets.mkdir(parents=True,exist_ok=True)
        for target,source in ((run/"RTYPE.PRG",prg),(assets/"rtype_sim.map",mp),
                              (assets/"gen_info.json",ROOT/"build/rtype/gen_info.json")):
            target.symlink_to(source)
        logic_test.ROOT=root
        logic_test.build_dir=lambda game:assets
        sys.argv=["logic_test.py",str(args.frames),"--seed",str(args.seed),"--snap","--list"]
        if args.windows:sys.argv += ["--windows",args.windows]
        if logic_test.main():raise SystemExit(1)
    elif args.dump:
        h=audit.Logic(args.variant)
        start=int(args.starts.split(",")[0])
        checkpoint=pickle.loads(gzip.decompress((BUILD/("seed%d_frame%d.pkl.gz"%(args.seed,start))).read_bytes()))
        h.load(checkpoint)
        ports=type("Ports",(),checkpoint["ports"].copy())()
        rng=random.Random();rng.setstate(checkpoint["rng"])
        audit.cover.press(ports,start,args.seed,rng,checkpoint["controls"].copy())
        h.frame(ports,True)
        (BUILD/("dump_"+args.variant+".pkl.gz")).write_bytes(gzip.compress(pickle.dumps(h.logical_state()),mtime=0))
    elif args.extra:
        extra(args.variant)
    elif args.focused:
        level.BUILD,level.Logic=BUILD,audit.Logic
        level.focused(args.variant)
    elif args.benchmark:
        audit.benchmark(args.variant,args.seed,list(map(int,args.starts.split(","))),args.frames)
    else:
        for variant in ("base",args.variant):
            subprocess.run([sys.executable,__file__,"--benchmark","--variant",variant,"--seed",str(args.seed),
                            "--starts",args.starts,"--frames",str(args.frames)],check=True)


if __name__=="__main__":main()
