#!/usr/bin/env python3
"""Verify the exact VIDCTRL.TOS in the pinned Hatari, including scanout pixels.

The optional native launcher tests a 60 Hz / cache-on starting desktop and
an idle Timer D. It does not patch the diagnostic or poke emulated IO.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import paths

HATARI=Path(os.environ.get('HATARI',str(ROOT.parent/'F030Arcade/third_party/hatari/build/src/hatari')))
TOS=Path(os.environ.get('TOS',str(ROOT.parent/'F030Arcade/third_party/tos/tos206de.img')))

LAUNCHER='''
 section text
start:
 move.l 4(sp),a5
 lea fixture_stack_end,sp
 move.l #fixture_stack_end,d0
 sub.l a5,d0
 move.l d0,-(sp)
 move.l a5,-(sp)
 clr.w -(sp)
 move.w #$4a,-(sp)
 trap #1
 lea 12(sp),sp
 moveq #0,d0
 move.l d0,-(sp)
 move.w #$20,-(sp)
 trap #1
 addq.l #6,sp
 move.l d0,old_ssp
 move.b $ffff820a.w,old_sync
 move.b $ffff8e21.w,old_speed
 move.b $fffffa1d.w,old_cd
 move.b #3,$ffff8e21.w
 clr.b $ffff820a.w
 and.b #$f0,$fffffa1d.w
 move.l old_ssp,-(sp)
 move.w #$20,-(sp)
 trap #1
 addq.l #6,sp
 clr.l -(sp)
 pea tail
 pea name
 clr.w -(sp)
 move.w #$4b,-(sp)
 trap #1
 lea 16(sp),sp
 clr.l -(sp)
 move.w #$20,-(sp)
 trap #1
 addq.l #6,sp
 move.l d0,old_ssp
 move.b old_cd,$fffffa1d.w
 move.b old_sync,$ffff820a.w
 move.b old_speed,$ffff8e21.w
 move.l old_ssp,-(sp)
 move.w #$20,-(sp)
 trap #1
 addq.l #6,sp
 clr.w -(sp)
 trap #1
 section data
name: dc.b 'VIDCTRL.TOS',0
tail: dc.b 0,13
 section bss
old_ssp: ds.l 1
old_speed: ds.b 1
old_sync: ds.b 1
old_cd: ds.b 1
 even
fixture_stack: ds.b 4096
fixture_stack_end:
'''


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(out,fixture=False):
    w=out/('hatari-60hz-idle-td' if fixture else 'hatari')
    w.mkdir(parents=True,exist_ok=True)
    shutil.copy(out/'VIDCTRL.TOS',w/'VIDCTRL.TOS')
    for p in [w/'VIDCTRL.TXT',*w.glob('*.png'),*w.glob('*-state.bin')]:p.unlink(missing_ok=True)
    symbols={m[2]:int(m[1],16) for m in re.finditer(r'0x([0-9a-f]+) (\w+):',(out/'VIDCTRL.MAP').read_text())}
    commands=[]
    for i,name in enumerate(['closed','top','both']):
        script=w/(name+'.ini')
        script.write_text(f"screenshot {w/(name+'.png')}\nsavebin {w/(name+'-state.bin')} 'TEXT+${symbols['phase']:x}' $100\n")
        commands.append(f"b ('TEXT+${symbols['phase']:x}').w = {i} && ('TEXT+${symbols['phase_frames']:x}').w = 500 :once :trace :quiet :file {script}")
    (w/'install.ini').write_text('\n'.join(commands)+'\n')
    (w/'arm.ini').write_text(f"b pc = TEXT && pc < $e00000 && (pc).l = $42a73f3c :once :trace :quiet :file {w/'install.ini'}\n")
    target=w/'VIDCTRL.TOS'
    if fixture:
        (w/'vcboot.s').write_text(LAUNCHER)
        subprocess.run([paths.VASM,'-m68000','-Ftos','-quiet','-o',str(w/'VCBOOT.TOS'),str(w/'vcboot.s')],check=True)
        target=w/'VCBOOT.TOS'
    cmd=[str(HATARI),'--machine','megaste','--memsize','4','--tos',str(TOS),'--fast-boot','true',
         '--fast-forward','true','--cpu-exact','true','--compatible','true','--sound','off',
         '--confirm-quit','off','--run-vbls','4000','--trace','video_sync,video_border_v,io_write',
         '--trace-file',str(w/'trace.log'),'--log-file',str(w/'hatari.log'),
         '--parse','prg:'+str(w/'arm.ini'),str(target)]
    with (w/'host.log').open('w') as log:
        proc=subprocess.Popen(cmd,env=os.environ|{'SDL_VIDEO_DRIVER':'dummy','SDL_AUDIO_DRIVER':'dummy'},stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                text=(w/'VIDCTRL.TXT').read_text(errors='replace') if (w/'VIDCTRL.TXT').exists() else ''
                if 'DONE completed' in text:break
                if proc.poll() is not None:raise RuntimeError((proc.returncode,text,w/'host.log'))
                time.sleep(.1)
            else:raise RuntimeError(f'timed out: {w}')
        finally:
            if proc.poll() is None:proc.terminate()
            proc.wait(timeout=5)
    assert 'DONE completed (1=yes,0=Esc abort): 00000001' in text,text
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in text,text
    cpu=[int(n,16) for n in re.search(r'CPU original / selected / end / restored FF8E21: (.*)',text)[1].split()]
    assert [v&3 for v in cpu]==([3,3,3,3] if fixture else [0,3,3,0]),cpu
    stages=[[int(v,16) for v in row.split()] for row in re.findall(r'^STAGE (.*)',text,re.M)]
    assert len(stages)==3,stages
    for i,s in enumerate(stages):
        assert len(s)==14 and s[0]==i,s
        assert 1000<=s[1]<=1010 and s[2]==0 and s[6]==0 and s[7]==0,s
        assert s[9:11]==[0,0] and s[11]==1 and s[12]&3==3 and s[13]&3==3,s
    assert stages[0][8]>=1000 and stages[1][8]<=2 and stages[2][8]==0,stages
    sampler=int(re.search(r'sampler available \(1=yes\): (\w+)',text)[1],16)
    if fixture:
        assert sampler==1,text
        for s in stages:assert s[3]>=990,s
        # The pinned Video_CalculateAddress can add LINEWID again when read
        # in a late horizontal phase even below the closed display. Record
        # its 96-byte readback range rather than calling it pixel damage.
        assert stages[0][4]==200*256 and stages[0][5]<=200*256+96,stages[0]
        assert stages[1][4]==229*256 and stages[1][5]<=229*256+96,stages[1]
        assert 266*256 <= stages[2][4]<=stages[2][5]<276*256,stages[2]
    trace=(w/'trace.log').read_text()
    controls=[int(v,16) for v in re.findall(r'IO write.b \$ffff8e21 = \$([0-9a-fA-F]+)',trace)]
    # Read/write upper bits are hardware-specific; only the documented low bits matter.
    assert ([v&3 for v in controls] in ([3,3,3],[3,3,3,0]) if fixture else [v&3 for v in controls]==[3,0]),controls
    # No Blitter control write occurs during the diagnostic (or the native launcher).
    assert not re.search(r'IO write.[bw] \$ffff8a3c',trace)
    raw=[]
    # Restrict pulses to PCs inside the unchanged diagnostic, excluding the
    # launcher's deliberate 60 Hz startup write and desktop restoration.
    # Code base comes from Hatari's evaluated TEXT expression in the callback.
    log_text=(w/'host.log').read_text()
    match=re.search(r"'TEXT\+\$%x' -> \$([0-9a-f]+)" % symbols['phase'],log_text)
    assert match,log_text
    text_base=int(match[1],16)-symbols['phase']
    for m in re.finditer(r'sync=(0x\w+) video_cyc_w=(\d+).*?pc=([0-9a-f]+)',trace):
        pc=int(m[3],16)
        if text_base<=pc<text_base+symbols['final_report']:
            raw.append((int(m[1],16),int(m[2])/2,pc))
    pulses=[(int(a[1]//512),a[1]%512,b[1]%512) for a,b in zip(raw,raw[1:])
            if a[0]==0 and b[0]==2 and 25*512<a[1]<270*512]
    top=[p for p in pulses if p[0]<100]; bottom=[p for p in pulses if p[0]>200]
    assert 1990<len(top)<2030 and 990<len(bottom)<1020,(len(top),len(bottom))
    assert all(p[0]==33 and 376<=p[1]<500 and 0<=p[2]<36 for p in top),Counter(top)
    assert all(p[0]==262 and 376<=p[1]<500 and 0<=p[2]<36 for p in bottom),Counter(bottom)
    reference=np.array(Image.open(out/'REFPIC.BMP').convert('RGB'))
    palette_words=np.frombuffer((out/'PALETTE.BIN').read_bytes(),'>u2')
    palette=np.stack([(((palette_words>>shift)&7)*2+((palette_words>>(shift+3))&1))*17
                      for shift in (8,4,0)],axis=1).astype(np.uint8)
    def unpack(data,h,w):
        words=np.frombuffer(data,'>u2').reshape(h,w//16,4)
        pixels=np.zeros((h,w),np.uint8)
        for p in range(4):
            for bit in range(16):pixels[:,bit::16]|=(((words[:,:,p]>>(15-bit))&1)<<p).astype(np.uint8)
        return palette[pixels]
    labels=(out/'LABELS.BIN').read_bytes()
    timers=(out/'TIMERS.BIN').read_bytes()
    pixel_results={}
    for i,(name,y,h) in enumerate([('closed',58,200),('top',0,229),('both',0,276)]):
        shot=np.array(Image.open(w/(name+'.png')).convert('RGB'))
        state=(w/(name+'-state.bin')).read_bytes()
        assert len(state)==256
        offset=symbols['countdown']-symbols['phase']
        countdown=int.from_bytes(state[offset:offset+2],'big')
        want=np.zeros((h,320,3),np.uint8)
        picture_rows=min(h-10,256)
        want[10:10+picture_rows]=reference[:picture_rows]
        want[32:48,:48]=unpack(labels[i*384:(i+1)*384],16,48)
        want[56:64,:48]=unpack(timers[countdown*192:(countdown+1)*192],8,48)
        want=np.repeat(np.repeat(want,2,0),2,1)
        got=shot[y:y+2*h,96:736]
        assert got.shape==want.shape,(name,got.shape,want.shape)
        different=int(np.count_nonzero(np.any(got!=want,axis=2)))
        assert different==0,(name,different)
        pixel_results[name]=dict(hardware_rows=h,picture_rows=picture_rows,countdown=countdown,different_pixels=different)
    result=dict(executable_sha256=digest(out/'VIDCTRL.TOS'),hatari_sha256=digest(HATARI),tos_sha256=digest(TOS),
                command=cmd,cpu=cpu,cpu_writes=controls,stages=stages,sampler_available=bool(sampler),
                pulse_histogram={str(k):v for k,v in sorted(Counter(pulses).items())},scanout=pixel_results,
                fixture='native 60Hz/cache-on/idle-Timer-D launcher' if fixture else 'normal TOS startup',
                hatari_commit=subprocess.check_output(['git','-C',str(HATARI.parents[2]),'rev-parse','HEAD'],text=True).strip(),
                scope='emulation regression; physical scanout still needs Darklord photos')
    (w/'RESULT.JSN').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/megaste-video-control')
    ap.add_argument('--fixture',action='store_true')
    args=ap.parse_args()
    verify(args.out.resolve(),args.fixture)
