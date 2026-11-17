#!/usr/bin/env python3
"""Build/package the unattended 16 MHz/cache-on bottom-border pulse sweep."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import numpy as np
from PIL import Image
import videoctrl as vc

ROOT=vc.ROOT
# One legacy poll, the delayed-poll centre, four start shifts, four widths.
CASES=[('OLD',0,101,17),('REF',1,101,17),
       ('E20',1,97,17),('E10',1,99,17),('L10',1,103,17),('L20',1,105,17),
       ('W13',1,101,13),('W15',1,101,15),('W19',1,101,19),('W21',1,101,21)]


def phases():
    rows=[]
    for i,(name,family,delay,width) in enumerate(CASES,1):
        rows.append(dict(label=f'B{i-1:02} TOP',seconds=4,gate=2,family=1,delay=101,width=17,case=0))
        rows.append(dict(label=f'P{i:02} {name}',seconds=10,gate=0,family=family,delay=delay,width=width,case=i))
    rows.append(dict(label='B10 TOP',seconds=4,gate=2,family=1,delay=101,width=17,case=0))
    return rows


def kernel():
    body=vc.gated_kernel()
    a=body.index('bd_low_open\tmacro');b=body.index('\nbd_top_open\tmacro',a)
    # Only the bottom macro changes; the known top path is retained verbatim.
    macro=r'''bd_low_open macro
	movem.l d3-d5/a1,-(sp)
	move.w low_gate,d3
	move.w bp_delay,d4
	move.w bp_width,d5
	tst.w bp_family
	bne bp_delay_prepare
	; Previous VIDCTRL's poll target and pulse sequence, variable width preloaded.
	lea bp_old_pulse(pc),a1
	move.l (a1),d2
	move.l 4(a1),d2
	move.l 8(a1),d2
	move.l 12(a1),d2
	move.l 16(a1),d2
	bd_poll
bp_old_pulse:
	move.b d3,$ffff820a.w
	nop
	move.w d5,d2
bp_old_width:
	dbf d2,bp_old_width
	move.b #2,$ffff820a.w
	bra bp_pulse_done
bp_delay_prepare:
	; Synchronize one DE falling edge earlier, then wait one cached scanline.
	; DBF #101 = 101 taken * 10 + final 14 = 1024 CPU cycles (512 video).
	addq.b #1,d0
	lea bp_delay_start(pc),a1
	move.l (a1),d2
	move.l 4(a1),d2
	move.l 8(a1),d2
	move.l 12(a1),d2
	move.l 16(a1),d2
	move.l 20(a1),d2
	bd_poll
bp_delay_start:
	dbf d4,bp_delay_start
bp_new_pulse:
	move.b d3,$ffff820a.w
	nop
	move.w d5,d2
bp_new_width:
	dbf d2,bp_new_width
	move.b #2,$ffff820a.w
bp_pulse_done:
	movem.l (sp)+,d3-d5/a1
	endm
'''
    return body[:a]+macro+body[b:]


def build(out,capture):
    out.mkdir(parents=True,exist_ok=True)
    check=vc.compare(capture)
    data,pixels,rgb=vc.decode(capture)
    assert check['differing_reference_pixels']==0
    assert not np.any(pixels[:,:48]) and not np.any(pixels[:,272:])
    frame=np.zeros((320,512),np.uint8);frame[10:266,:320]=pixels
    (out/'FRAME.BIN').write_bytes(vc.planar(frame))
    (out/'PALETTE.BIN').write_bytes(data[48:80])
    Image.fromarray(rgb[pixels]).save(out/'REFPIC.BMP')
    font={'R':['11110','10001','10001','11110','10100','10010','10001'],
          'F':['11111','10000','10000','11110','10000','10000','10000'],
          'W':['10001','10001','10001','10101','10101','10101','01010'],
          'D':['11110','10001','10001','10001','10001','10001','11110'],
          '+':['00000','00100','00100','11111','00100','00100','00000'],
          '-':['00000','00000','00000','11111','00000','00000','00000']}
    vc.FONT.update(font)
    colour=int(np.argmax(rgb.astype(int).sum(axis=1)))
    rows=phases()
    labels=[]
    for row in rows:
        shift=(row['delay']-101)*5
        setting=f"S{shift:+d}W{row['width']}"
        labels.append(vc.tile([row['label'],setting,'16C ON'],colour))
    (out/'LABELS.BIN').write_bytes(b''.join(labels))
    (out/'TIMERS.BIN').write_bytes(b''.join(vc.tile([f'{n:02} SEC'],colour) for n in range(21)))
    (out/'bp_config.i').write_text(f'PHASE_COUNT = {len(rows)}\n')
    (out/'bp_phases.i').write_text(''.join('\tdc.w '+','.join(str(r[k]) for k in ['seconds','gate','family','delay','width','case'])+'\n' for r in rows))
    (out/'vc_borders.i').write_text(kernel())
    for name in ['videoctrl.s','bottomprobe.s','bottomprobe.i']:
        shutil.copy(ROOT/'tools'/name,out/name)
    shutil.copy(vc.paths.RT_INCLUDE/'ikbd.s',out/'ikbd.s')
    names=['videoctrl.s','bottomprobe.s','bottomprobe.i','ikbd.s','vc_borders.i',
           'bp_config.i','bp_phases.i','FRAME.BIN','PALETTE.BIN','LABELS.BIN','TIMERS.BIN']
    source_hashes={n:vc.sha(out/n) for n in names}
    identity=hashlib.sha256(json.dumps(source_hashes,sort_keys=True).encode()).hexdigest()[:16]
    (out/'vc_build.i').write_text(f"\tdc.b 'Build {identity}',13,10\n")
    subprocess.run([vc.paths.VASM,'-m68000','-Fvobj','-quiet','-nowarn=2047','-I'+str(out),'-o',str(out/'bottom.o'),str(out/'bottomprobe.s')],check=True)
    subprocess.run([vc.paths.VLINK,'-b','ataritos','-s','-o',str(out/'BOTTOM.TOS'),'-M'+str(out/'BOTTOM.MAP'),str(out/'bottom.o')],check=True)
    manifest=dict(build=identity,executable_sha256=vc.sha(out/'BOTTOM.TOS'),source_sha256=source_hashes,
                  capture_sha256=vc.sha(capture),capture_verification=check,phases=rows,
                  nominal_seconds=sum(r['seconds'] for r in rows),cpu='16 MHz/cache on throughout',
                  timer_b_edge='DE falling (AER bit3 cleared), original full AER restored',
                  shared_border_sha256=vc.sha(vc.paths.RT_INCLUDE/'borders.s'),
                  top_kernel='same gated/warmed top code as VIDCTRL 1',
                  start_shift_units='nominal 8 MHz video cycles, 5 per DBF iteration; verify actual IO times in trace',
                  scope='exploratory pulse sweep, not a physically validated fix')
    (out/'BUILD.JSN').write_text(json.dumps(manifest,indent=2)+'\n')
    for dst,src in [('README.TXT','megaste-bottom-probe-readme.txt'),('MESSAGE.TXT','megaste-bottom-probe-message.txt')]:
        (out/dst).write_bytes((ROOT/'docs'/src).read_text().replace('\n','\r\n').encode('ascii'))
    for n in ['bottomprobe.py','bottomprobe_test.py','videoctrl.py']:
        shutil.copy(ROOT/'tools'/n,out/n)
    with zipfile.ZipFile(out/'SOURCE.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for n in names+['vc_build.i','BOTTOM.MAP','bottomprobe.py','bottomprobe_test.py','videoctrl.py']:
            z.write(out/n,n)
    package=['BOTTOM.TOS','REFPIC.BMP','README.TXT','MESSAGE.TXT','BUILD.JSN','SOURCE.ZIP']
    (out/'SHA256.TXT').write_bytes(''.join(f'{vc.sha(out/n)}  {n}\r\n' for n in package).encode('ascii'))
    with zipfile.ZipFile(out/'BOTTOM.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for n in package+['SHA256.TXT']:z.write(out/n,'BOTTOM/'+n)
    print(out/'BOTTOM.ZIP',identity,manifest['executable_sha256'])
    return manifest


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=ROOT/'build/megaste-bottom-probe')
    args=ap.parse_args();build(args.out.resolve(),args.capture.resolve())
