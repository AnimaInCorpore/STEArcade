#!/usr/bin/env python3
"""Check the delivered probe, all phase transitions, pulses, edge and restoration.

Screenshots/guest reads use one persistent breakpoint and a blocking debugger
reply FIFO. No guest IO pokes are used. Exploratory scanouts are characterized,
not all required to be full-height: some timings intentionally miss the window.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

import numpy as np
from PIL import Image
import bottomprobe as bp
import videoctrl_test as vc_test

ROOT=bp.ROOT


def symbols(out):
    return {m[2]:int(m[1],16) for m in re.finditer(r'0x([0-9a-f]+) (\w+):',(out/'BOTTOM.MAP').read_text())}


def native_masks(out):
    from machine68k import Register as R
    from sim import Sim
    sim=Sim(out/'BOTTOM.TOS');sim.mem.set_trace_mode(False)
    sym={k:v+sim.base for k,v in symbols(out).items()}
    rows=sym['bp_restore_rows'];sim.mem.w16(sym['bp_restore_n'],0);sim.mem.w32(sym['restore_bad'],0)
    tests=[(0x27,0x47,3,0),(0x27,0x46,3,1),(0xabc,0xfabc,0xfff,0),(0x12345678,0x12345670,0xffffffff,8)]
    for i,(expected,actual,mask,diff) in enumerate(tests):
        sim.mem.w32(0x8000,0x600);sim.cpu.w_reg(R.A7,0x8000);sim.cpu.w_sr(0x2700)
        for r,val in {R.D0:0xffff8e21,R.D1:1,R.D2:expected,R.D3:actual,R.D4:mask,R.A3:rows+i*24}.items():
            sim.cpu.w_reg(r,val)
        sim.cpu.w_pc(sym['bp_restore_add']);sim.cpu.execute(3000)
        assert sim.cpu.r_pc()==0x600,hex(sim.cpu.r_pc())
        row=struct.unpack('>6L',bytes(sim.mem.r_block(rows+i*24,24)))
        assert row==(0xffff8e21,1,expected,actual,mask,diff),row
    assert sim.mem.r16(sym['bp_restore_n'])==4 and sim.mem.r32(sym['restore_bad'])==2
    return dict(cases=4,raw_upper_bits_retained=True,undefined_bits_ignored=True,defined_bit_faults_detected=True)


def unpack(data,h,w,palette):
    words=np.frombuffer(data,'>u2').reshape(h,w//16,4);pixels=np.zeros((h,w),np.uint8)
    for p in range(4):
        for bit in range(16):pixels[:,bit::16]|=(((words[:,:,p]>>(15-bit))&1)<<p).astype(np.uint8)
    return palette[pixels]


def pulse_profiles(raw,sym,base,phases,aborted=False):
    """Recover B/P runs from the gate writes themselves, not host time."""
    starts={base+sym['bp_old_pulse']:0,base+sym['bp_new_pulse']:1}
    runs=[]
    for a,b in zip(raw,raw[1:]):
        if a[2] not in starts:continue
        assert a[0] in (0,2) and b[0]==2,(a,b)
        duration=b[1]-a[1]
        assert 60<=duration<=140,(a,b)
        point=(int(a[1]//512),a[1]%512,b[1]%512,duration,starts[a[2]])
        if not runs or runs[-1][0]!=a[0]:runs.append((a[0],[]))
        runs[-1][1].append(point)
    if not aborted:assert len(runs)==len(phases),(len(runs),len(phases))
    profiles={}
    for (gate,points),phase in zip(runs,phases):
        assert gate==phase['gate'],(gate,phase)
        assert all(p[0]==262 and p[4]==phase['family'] for p in points),(phase,Counter(points))
        if not aborted:assert phase['seconds']*50-2<=len(points)<=phase['seconds']*50+10,(phase,len(points))
        start=float(np.median([p[1] for p in points]));duration=float(np.median([p[3] for p in points]))
        profiles[phase['label']]=dict(samples=len(points),median_start=start,median_duration=duration,
            histogram={str(k):v for k,v in sorted(Counter(points).items())})
    if not aborted:
        ref=profiles['P02 REF']
        for phase in phases:
            if phase['gate'] or phase['family']==0:continue
            got=profiles[phase['label']]
            nominal_start=(phase['delay']-101)*5
            nominal_duration=(phase['width']-17)*5
            assert abs(got['median_start']-ref['median_start']-nominal_start)<=2,(phase,got,ref)
            assert abs(got['median_duration']-ref['median_duration']-nominal_duration)<=2,(phase,got,ref)
    return profiles


def verify(out,fixture=False,abort=False):
    tag='hatari-abort' if abort else ('hatari-60hz-rising-idle-td' if fixture else 'hatari')
    w=out/tag;w.mkdir(parents=True,exist_ok=True)
    for p in [w/'BOTTOM.TXT',*w.glob('stage-*.png'),*w.glob('stage-*.bin')]:p.unlink(missing_ok=True)
    shutil.copy(out/'BOTTOM.TOS',w/'BOTTOM.TOS');sym=symbols(out)
    manifest=json.loads((out/'BUILD.JSN').read_text());phases=manifest['phases']
    data_fifo=w/'sample.fifo';reply_fifo=w/'reply.fifo'
    for p in [data_fifo,reply_fifo]:p.unlink(missing_ok=True);os.mkfifo(p)
    fd=os.open(data_fifo,os.O_RDWR|os.O_NONBLOCK)
    (w/'step.ini').write_text(f"savebin {data_fifo} 'TEXT+${sym['phase']:x}' $100\nparse {reply_fifo}\n")
    (w/'install.ini').write_text(f"b pc = 'TEXT+${sym['vbl']:x}' && ('TEXT+${sym['phase_frames']:x}').w = 125 :trace :quiet :file {w/'step.ini'}\n")
    # Arm once at emulator startup; dynamic TEXT follows Pexec to the child.
    # The native launcher has a different first opcode, so it cannot match.
    (w/'arm.ini').write_text(f"b pc = TEXT && pc < $e00000 && (pc).l = $42a73f3c :once :trace :quiet :file {w/'install.ini'}\n")
    target=w/'BOTTOM.TOS'
    if fixture:
        launcher=vc_test.LAUNCHER.replace('VIDCTRL.TOS','BOTTOM.TOS')
        launcher=launcher.replace(' move.b $fffffa1d.w,old_cd',' move.b $fffffa1d.w,old_cd\n move.b $fffffa03.w,old_aer\n bset #3,$fffffa03.w')
        launcher=launcher.replace(' move.b old_cd,$fffffa1d.w',' move.b old_cd,$fffffa1d.w\n move.b old_aer,$fffffa03.w')
        launcher=launcher.replace('old_cd: ds.b 1','old_cd: ds.b 1\nold_aer: ds.b 1')
        (w/'boot.s').write_text(launcher)
        subprocess.run([bp.vc.paths.VASM,'-m68000','-Ftos','-quiet','-o',str(w/'BOOT.TOS'),str(w/'boot.s')],check=True)
        target=w/'BOOT.TOS'
    fifo=w/'commands.fifo';fifo.unlink(missing_ok=True)
    cmd=[str(vc_test.HATARI),'--machine','megaste','--memsize','4','--tos',str(vc_test.TOS),
         '--fast-boot','true','--fast-forward','true','--cpu-exact','true','--compatible','true',
         '--sound','off','--confirm-quit','off','--run-vbls','9000','--cmd-fifo',str(fifo),
         '--trace','video_sync,video_border_v,io_write','--trace-file',str(w/'trace.log'),
         '--parse',str(w/'arm.ini'),str(target)]
    seen=set();pending=bytearray()
    with (w/'host.log').open('w') as log:
        proc=subprocess.Popen(cmd,env=os.environ|{'SDL_VIDEO_DRIVER':'dummy','SDL_AUDIO_DRIVER':'dummy'},stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                try:pending.extend(os.read(fd,4096))
                except BlockingIOError:pass
                while len(pending)>=256:
                    state=bytes(pending[:256]);del pending[:256]
                    phase=int.from_bytes(state[:2],'big');assert phase not in seen,(phase,'duplicate callback')
                    assert int.from_bytes(state[2:4],'big')==125
                    seen.add(phase);(w/f'stage-{phase:02}.bin').write_bytes(state)
                    # This opens only once Hatari is in its blocking parse callback.
                    answer=os.open(reply_fifo,os.O_WRONLY|os.O_NONBLOCK)
                    commands=f"screenshot {w/f'stage-{phase:02}.png'}\nsavebin {w/f'config-{phase:02}.bin'} 'TEXT+${sym['bp_seconds']:x}' $10\n"
                    os.write(answer,commands.encode());os.close(answer)
                    print(tag,'phase',phase,phases[phase]['label'],flush=True)
                    if abort:
                        time.sleep(.02)
                        with fifo.open('w') as f:f.write('hatari-event keydown 0x01\n')
                        time.sleep(.1)
                        with fifo.open('w') as f:f.write('hatari-event keyup 0x01\n')
                text=(w/'BOTTOM.TXT').read_text(errors='replace') if (w/'BOTTOM.TXT').exists() else ''
                if 'DONE completed' in text:break
                if proc.poll() is not None:raise RuntimeError((proc.returncode,text,w/'host.log'))
                time.sleep(.01)
            else:raise RuntimeError(('timeout',w,seen))
        finally:
            os.close(fd)
            # Release a parse reader before terminating, even on a host assertion.
            try:
                answer=os.open(reply_fifo,os.O_WRONLY|os.O_NONBLOCK);os.write(answer,b'\n');os.close(answer)
            except OSError:pass
            if proc.poll() is None:proc.terminate()
            proc.wait(timeout=5)
    assert f'DONE completed (1=yes,0=Esc abort): {0 if abort else 1:08X}' in text,text
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in text,text
    rows=[[int(x,16) for x in row.split()] for row in re.findall(r'^STAGE (.*)',text,re.M)]
    assert len(rows)==len(phases)
    cpu=[int(v,16) for v in re.search(r'CPU original / selected / end / restored FF8E21: (.*)',text)[1].split()]
    assert [v&3 for v in cpu]==([3,3,3,3] if fixture else [0,3,3,0]),cpu
    aer=[int(v,16) for v in re.search(r'AER original / selected / end / restored.*: (.*)',text)[1].split()]
    assert aer[1:3]==[aer[0]&~8]*2 and aer[3]==aer[0],aer
    if fixture:assert aer[0]&8,aer
    restore=[[int(x,16) for x in row.split()] for row in re.findall(r'^RESTORE addr size expected actual mask diff: (.*)',text,re.M)]
    assert len(restore)==(42 if fixture else 41),len(restore)
    assert all((r[2]^r[3])&r[4]==r[5]==0 for r in restore),restore
    assert next(r for r in restore if r[0]==0xffff8e21)[4]==3
    assert {r[0] for r in restore if r[1]==4}=={0x68,0x70,0x110,0x118,0x120,0x134}
    if not abort:
        assert seen==set(range(len(phases))),seen
        for i,(row,phase) in enumerate(zip(rows,phases)):
            assert len(row)==17 and row[0]==i,row
            assert phase['seconds']*50<=row[1]<=phase['seconds']*50+10,row
            assert row[2]==row[7]==row[9]==row[10]==row[16]==0,row
            assert row[11]==1 and row[12]&3==row[13]&3==3,row
            assert row[14]&8==row[15]&8==0,row
            config=struct.unpack('>6H4B',(w/f'config-{i:02}.bin').read_bytes())
            assert config[:5]==(phase['seconds'],phase['seconds']*50,phase['family'],phase['delay'],phase['width']),config
        if fixture:assert all(r[3]>=p['seconds']*50-10 for r,p in zip(rows,phases))
    trace=(w/'trace.log').read_text()
    cpu_writes=[int(v,16)&3 for v in re.findall(r'IO write.b \$ffff8e21 = \$([0-9a-fA-F]+)',trace)]
    assert (cpu_writes in ([3,3,3],[3,3,3,0]) if fixture else cpu_writes==[3,0]),cpu_writes
    assert not re.search(r'IO write.[bw] \$ffff8a3c',trace)
    # Relative symbol expressions are evaluated at program load, so parse the
    # absolute vbl address from the installed debugger breakpoint's own output.
    logs=(w/'host.log').read_text()
    m=re.search(r"'TEXT\+\$%x' -> \$([0-9a-f]+)"%sym['vbl'],logs);assert m,logs[-2000:]
    base=int(m[1],16)-sym['vbl']
    raw=[]
    for m in re.finditer(r'sync=(0x\w+) video_cyc_w=(\d+).*?pc=([0-9a-f]+)',trace):
        pc=int(m[3],16)
        if base<=pc<base+sym['final_report']:raw.append((int(m[1],16),int(m[2])/2,pc))
    hist=Counter((int(a[1]//512),a[1]%512,b[1]%512,a[2]-base) for a,b in zip(raw,raw[1:])
                 if a[0]==0 and b[0]==2 and 25*512<a[1]<270*512)
    profiles=pulse_profiles(raw,sym,base,phases,abort)
    if not abort:
        top=sum(n for (line,_,_,_),n in hist.items() if line==33)
        bottom=sum(n for (line,_,_,_),n in hist.items() if line==262)
        assert top>=sum(p['seconds']*50 for p in phases)-4 and bottom>=4990,(top,bottom,hist)
        assert all(line in (33,262) for line,_,_,_ in hist),hist
        assert all(376<=start<500 and 0<=end<36 for line,start,end,_ in hist if line==33),hist
    palette_words=np.frombuffer((out/'PALETTE.BIN').read_bytes(),'>u2')
    palette=np.stack([(((palette_words>>shift)&7)*2+((palette_words>>(shift+3))&1))*17 for shift in (8,4,0)],axis=1).astype(np.uint8)
    labels=(out/'LABELS.BIN').read_bytes();timers=(out/'TIMERS.BIN').read_bytes()
    reference=np.array(Image.open(out/'REFPIC.BMP').convert('RGB'))
    scanout={}
    for i in sorted(seen):
        state=(w/f'stage-{i:02}.bin').read_bytes();offset=sym['countdown']-sym['phase']
        countdown=int.from_bytes(state[offset:offset+2],'big');phase=phases[i]
        shot=np.array(Image.open(w/f'stage-{i:02}.png').convert('RGB'))
        # All stages retain the known top opening. Compare the complete common
        # 229-line display, including HUD, and characterize the lower extension.
        expected=np.zeros((276,320,3),np.uint8);expected[10:266]=reference
        expected[32:56,:48]=unpack(labels[i*576:(i+1)*576],24,48,palette)
        expected[56:64,:48]=unpack(timers[countdown*192:(countdown+1)*192],8,48,palette)
        want=np.repeat(np.repeat(expected,2,0),2,1);got=shot[:552,96:736]
        common=int(np.count_nonzero(np.any(got[:458]!=want[:458],axis=2)))
        full=int(np.count_nonzero(np.any(got!=want,axis=2)))
        # Timings outside the prefetch window may legitimately scramble the
        # lower extension; a bad TOP recovery is always a regression in Hatari.
        if phase['gate']==2:assert common==0,(i,common)
        elif phase['case'] in (1,2):assert common==full==0,(i,common,full)
        scanout[phase['label']]=dict(common_different_pixels=common,full_different_pixels=full,countdown=countdown)
    result=dict(build=manifest['build'],executable_sha256=bp.vc.sha(out/'BOTTOM.TOS'),
                hatari_sha256=bp.vc.sha(vc_test.HATARI),hatari_commit=subprocess.check_output(['git','-C',str(vc_test.HATARI.parents[2]),'rev-parse','HEAD'],text=True).strip(),
                command=cmd,fixture=fixture,aborted=abort,cpu=cpu,cpu_writes=cpu_writes,aer=aer,restore_rows=len(restore),
                native_masks=native_masks(out),stages=rows,pulse_profiles=profiles,
                pulse_histogram={str(k):v for k,v in sorted(hist.items())},scanout=scanout,
                scope='emulator characterization; physical pulse settings not validated')
    (w/'RESULT.JSN').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/megaste-bottom-probe')
    ap.add_argument('--fixture',action='store_true')
    ap.add_argument('--abort',action='store_true')
    args=ap.parse_args();verify(args.out.resolve(),args.fixture,args.abort)
