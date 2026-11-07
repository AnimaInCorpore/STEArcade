#!/usr/bin/env python3
"""Trace shared border timing in pinned Hatari, without ROMs or the long RAM suite.

Examples:
  python tools/dltest_timing.py --mode 2 --seconds 50
  python tools/dltest_timing.py --mode 2 --pad 12288
  python tools/dltest_timing.py --machine ste --mode 0
"""
import argparse
from collections import Counter
import json
import gzip
import os
from pathlib import Path
import re
import subprocess
import time
from PIL import Image
import dltest


def scanout_check(path, reference):
    image=Image.open(path).convert('RGB')
    expected=Image.open(reference).convert('RGB')
    width,height=image.size
    raw=image.tobytes()
    white=re.compile(b'(?:\xee\xee\xee){320,}')
    for y in range(height):
        for match in white.finditer(raw[y*width*3:(y+1)*width*3]):
            x=match.start()//3
            run=(match.end()-match.start())//3
            scale=run//320
            if run%320 or not 1<=scale<=4 or y+256*scale>height:continue
            actual=image.crop((x,y,x+320*scale,y+256*scale)).resize((320,256),Image.Resampling.NEAREST)
            differences=[]
            for yy in range(256):
                for xx in range(320):
                    if 256<=xx<320 and 8<=yy<16:continue  # deliberately visible countdown
                    if actual.getpixel((xx,yy))!=expected.getpixel((xx,yy)):
                        differences.append((xx,yy))
            assert not differences,(str(path),len(differences),differences[:16])
            return dict(origin=[x,y],scale=scale,changed_pixels_outside_timer=0)
    raise AssertionError(('test picture not found in monitor capture',str(path)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--machine',choices=['ste','megaste'],default='megaste')
    ap.add_argument('--mode',type=int,choices=[0,1,2],default=2)
    ap.add_argument('--seconds',type=int,default=3,help='seconds EACH of idle and mixed-HOG load')
    ap.add_argument('--pad',type=int,default=0,help='shift code/cache indices, bytes (even)')
    ap.add_argument('--out',type=Path)
    ap.add_argument('--check-control',action='store_true',help='trace and assert every FF8E21 write')
    ap.add_argument('--borders',type=Path,help='use a saved borders.s for baseline comparison')
    args=ap.parse_args()
    assert 1<=args.seconds<=300 and 0<=args.pad<=32766 and args.pad%2==0
    assert args.machine=='megaste' or args.mode==0
    work=(args.out or dltest.ROOT/'build/border-timing'/f'{args.machine}-{args.mode}-{args.pad}').resolve()
    dltest.build(work,quick=True)
    if args.borders:
        body=args.borders.read_text();hook='\tbd_check_late bd_late_off'
        (work/'dltest_borders.i').write_text(body.replace(hook,hook+'\n\tbsr border_off_sample'))
    defs=['QUICK=1','BORDER_ONLY=1',f'BORDER_TARGET={args.mode}',f'BORDER_SECONDS={args.seconds}']
    if args.pad:defs.append(f'BORDER_PAD={args.pad}')
    cmd=[dltest.paths.VASM,'-m68000','-Ftos','-quiet','-nowarn=2047']+['-D'+d for d in defs]
    cmd+=['-I'+str(dltest.paths.RT_INCLUDE),'-I'+str(work),'-I'+str(dltest.ROOT/'tools'),
          '-o',str(work/'DLTEST.TOS'),str(dltest.ROOT/'tools/dltest.s')]
    subprocess.run(cmd,check=True)
    result=work/'DLTEST.TXT';result.unlink(missing_ok=True)
    fifo=work/'commands.fifo';fifo.unlink(missing_ok=True)
    log=(work/'host.log').open('w')
    hatari=os.environ.get('HATARI','/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari')
    tos=os.environ.get('TOS','/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img')
    proc=subprocess.Popen([hatari,'--machine',args.machine,'--memsize','4','--tos',tos,'--fast-boot','true',
        '--cpu-exact','true','--compatible','true','--sound','off','--confirm-quit','off',
        '--cmd-fifo',str(fifo),'--trace','video_sync,video_border_v'+(',io_write' if args.check_control else ''),
        '--trace-file',str(work/'trace.log'),'--log-file',str(work/'hatari.log'),str(work/'DLTEST.TOS')],stdout=log,stderr=log)
    shots=set();start=None
    try:
        deadline=time.monotonic()+max(60,args.seconds*6+30)
        while time.monotonic()<deadline:
            text=result.read_text(errors='replace') if result.exists() else ''
            if 'FATAL unexpected' in text:raise RuntimeError(text)
            if 'DONE -' in text:break
            if 'BEGIN OPEN BORDERS' in text:
                if start is None:start=time.monotonic()
                for label,after in [('idle',.7),('load',args.seconds+0.6)]:
                    if label not in shots and time.monotonic()-start>after and fifo.exists():
                        with fifo.open('w') as f:f.write(f'hatari-debug screenshot {work/(label+".png")}\n')
                        shots.add(label)
            if proc.poll() is not None:raise RuntimeError('Hatari exited')
            time.sleep(.05)
        else:raise RuntimeError(f'timeout: {work}')
    finally:
        proc.terminate();proc.wait(timeout=5);log.close()
    assert f'MODE end FF8E21 readback (STE=0): {([0,2,3][args.mode]):08X}' in text,text
    counts=re.search(r'BORDERS post-picture samples / missing frames after warmup: (\w+) (\w+)',text)
    samples,missing=[int(x,16) for x in counts.groups()]
    assert samples>=args.seconds*95-12,(samples,missing,text)
    if args.mode==2:
        assert missing==0,(samples,missing,text)
    assert (work/f'OPEN{args.mode}.BMP').read_bytes()==(work/'REFERENCE/OPENCPU.BMP').read_bytes()
    trace=(work/'trace.log').read_text(errors='replace')
    control=[]
    if args.check_control:
        control=[int(v,16) for v in re.findall(r'IO write.b \$ffff8e21 = \$([0-9a-fA-F]+)',trace)]
        assert control==[0,[0,2,3][args.mode],0],control
    changes=[]
    for line in trace.splitlines():
        m=re.match(r'sync=(0x\w+) .*line_cyc_w=(\d+).*nHBL=(\d+)/video_hbl_w=(\d+)',line)
        if m:changes.append((int(m[1],16),int(m[2]),int(m[4])))
    # Line index in log can shift when the write itself changes frequency. Absolute
    # frame time is reconstructed from raw CPU clock cycles instead, below.
    raw=[]
    for line in trace.splitlines():
        m=re.match(r'sync=(0x\w+) video_cyc_w=(\d+).*pc=([0-9a-f]+)',line)
        if m:
            cycle=int(m[2])/(2 if args.mode else 1)
            raw.append((int(m[1],16),cycle,int(m[3],16)))
    pulses=[]
    for a,b in zip(raw,raw[1:]):
        if a[0]==0 and b[0]==2 and 25*512<a[1]<270*512:
            pulses.append(dict(line=int(a[1]//512),start=a[1]%512,end=b[1]%512,pc=a[2]))
    warm=pulses[8:]
    top=[p for p in warm if p['line']<100];bottom=[p for p in warm if p['line']>200]
    assert len(top)>args.seconds*80 and len(bottom)>args.seconds*80,(len(top),len(bottom))
    if args.mode==2:
        assert all(p['line']==33 and 376<=p['start']<500 and 0<=p['end']<36 for p in top),Counter((p['line'],p['start'],p['end']) for p in top)
        assert all(p['line']==262 and 376<=p['start']<500 and 0<=p['end']<36 for p in bottom),Counter((p['line'],p['start'],p['end']) for p in bottom)
    scanouts={}
    for label in ['idle','load']:
        path=work/(label+'.png')
        if path.exists() and args.mode==2:scanouts[label]=scanout_check(path,work/'REFERENCE/OPENCPU.BMP')
    data=dict(border_source_sha256=dltest.sha(args.borders or dltest.paths.RT_INCLUDE/'borders.s'),
              executable_sha256=dltest.sha(work/'DLTEST.TOS'),scanouts=scanouts,machine=args.machine,mode=args.mode,pad=args.pad,seconds_per_phase=args.seconds,
              samples=samples,missing_frames=missing,control_writes=control,top_pulses=len(top),bottom_pulses=len(bottom),
              top_histogram=[[list(k),v] for k,v in Counter((p['line'],p['start'],p['end']) for p in top).items()],
              bottom_histogram=[[list(k),v] for k,v in Counter((p['line'],p['start'],p['end']) for p in bottom).items()])
    (work/'timing.json').write_text(json.dumps(data,indent=2)+'\n')
    retained='\n'.join(line for line in trace.splitlines() if 'IO write' not in line or '8e21' in line)
    with gzip.open(work/'trace.log.gz','wt') as f:f.write(retained+'\n')
    (work/'trace.log').unlink()
    print(json.dumps(data),flush=True)


if __name__=='__main__':main()
