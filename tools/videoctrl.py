#!/usr/bin/env python3
"""Build the controlled, fixed-picture Mega STE border test (no ROM required at run time)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'engine'), str(ROOT/'games/gunsmoke/tools')]
import paths
import numpy as np
from PIL import Image
from megaste_capture import decode, compare

FONT = {
 ' ':['00000']*7,
 '0':['01110','10001','10011','10101','11001','10001','01110'],
 '1':['00100','01100','00100','00100','00100','00100','01110'],
 '2':['01110','10001','00001','00010','00100','01000','11111'],
 '3':['11110','00001','00001','01110','00001','00001','11110'],
 '4':['00010','00110','01010','10010','11111','00010','00010'],
 '5':['11111','10000','10000','11110','00001','00001','11110'],
 '6':['01110','10000','10000','11110','10001','10001','01110'],
 '7':['11111','00001','00010','00100','01000','01000','01000'],
 '8':['01110','10001','10001','01110','10001','10001','01110'],
 '9':['01110','10001','10001','01111','00001','00001','01110'],
 'A':['01110','10001','10001','11111','10001','10001','10001'],
 'B':['11110','10001','10001','11110','10001','10001','11110'],
 'C':['01111','10000','10000','10000','10000','10000','01111'],
 'E':['11111','10000','10000','11110','10000','10000','11111'],
 'H':['10001','10001','10001','11111','10001','10001','10001'],
 'L':['10000','10000','10000','10000','10000','10000','11111'],
 'N':['10001','11001','10101','10011','10001','10001','10001'],
 'O':['01110','10001','10001','10001','10001','10001','01110'],
 'P':['11110','10001','10001','11110','10000','10000','10000'],
 'S':['01111','10000','10000','01110','00001','00001','11110'],
 'T':['11111','00100','00100','00100','00100','00100','00100'],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def planar(pixels):
    h,w = pixels.shape
    assert w % 16 == 0
    words = np.zeros((h,w//16,4),dtype='>u2')
    for p in range(4):
        for bit in range(16):
            words[:,:,p] |= (((pixels[:,bit::16] >> p) & 1).astype(np.uint16) << (15-bit))
    return words.tobytes()


def tile(lines, colour):
    image=np.zeros((8*len(lines),48),np.uint8)
    for line,text in enumerate(lines):
        assert len(text)*6 <= 48
        for i,ch in enumerate(text):
            for y,row in enumerate(FONT[ch]):
                for x,bit in enumerate(row):
                    if bit=='1':image[line*8+y,i*6+x]=colour
    return planar(image)


def gated_kernel():
    """A test-only copy: d3=0 enables a pulse, d3=2 makes it a same-path no-op.

    MOVE.B D3,abs.w + NOP replaces CLR.B abs.w. Values are loaded before the
    warmed/polled region, and the extra kernel word is explicitly warmed.
    Production border source and its delay constants remain unchanged.
    """
    body=(paths.RT_INCLUDE/'borders.s').read_text()
    anchor='bd_fast_top:\n\tlea .wait(pc),a0'
    assert body.count(anchor)==1
    body=body.replace(anchor,'bd_fast_top:\n\tmove.w top_gate,d3\n\tlea .wait(pc),a0')
    anchor='\tmove.l 28(a0),d0\n\tmoveq #BD_FAST_TOP_DELAY,d2'
    assert body.count(anchor)==1
    body=body.replace(anchor,'\tmove.l 28(a0),d0\n\tmove.l 32(a0),d0\n\tmoveq #BD_FAST_TOP_DELAY,d2')
    a=body.index('bd_fast_top:'); b=body.index('; bd_speed_poll:',a)
    part=body[a:b]
    assert part.count('\tclr.b $ffff820a.w')==1
    part=part.replace('\tclr.b $ffff820a.w','\tmove.b d3,$ffff820a.w\n\tnop')
    body=body[:a]+part+body[b:]
    a=body.index('bd_low_open\tmacro'); b=body.index('\nbd_top_open\tmacro',a)
    part=body[a:b]
    part=part.replace('\ttst.b bd_fast','\tmove.l d3,-(sp)\n\tmove.w low_gate,d3\n\ttst.b bd_fast',1)
    part=part.replace('\tclr.b $ffff820a.w','\tmove.b d3,$ffff820a.w\n\tnop')
    part=part.replace('.done\\@:\n','.done\\@:\n\tmove.l (sp)+,d3\n')
    body=body[:a]+part+body[b:]
    return body


def build(out,capture):
    out.mkdir(parents=True,exist_ok=True)
    verification=compare(capture)
    data,pixels,rgb=decode(capture)
    assert verification['differing_reference_pixels']==0
    assert not np.any(pixels[:,:48]) and not np.any(pixels[:,272:])
    image=np.zeros((320,512),np.uint8)
    image[10:266,:320]=pixels
    (out/'FRAME.BIN').write_bytes(planar(image))
    (out/'PALETTE.BIN').write_bytes(data[48:80])
    colour=int(np.argmax(rgb.astype(int).sum(axis=1)))
    (out/'LABELS.BIN').write_bytes(b''.join(tile([s,'16C ON'],colour) for s in ['A CLOSE','B TOP','C BOTH']))
    (out/'TIMERS.BIN').write_bytes(b''.join(tile([f'{n:02} SEC'],colour) for n in range(21)))
    Image.fromarray(rgb[pixels]).save(out/'REFPIC.BMP')
    (out/'vc_borders.i').write_text(gated_kernel())
    shutil.copy(paths.RT_INCLUDE/'ikbd.s',out/'ikbd.s')
    shutil.copy(ROOT/'tools/videoctrl.s',out/'videoctrl.s')
    sources=['videoctrl.s','vc_borders.i','ikbd.s','FRAME.BIN','PALETTE.BIN','LABELS.BIN','TIMERS.BIN']
    hashes={name:sha(out/name) for name in sources}
    build_id=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:16]
    (out/'vc_build.i').write_text(f"\tdc.b 'Build {build_id}',13,10\n")
    subprocess.run([paths.VASM,'-m68000','-Fvobj','-quiet','-nowarn=2047','-I'+str(out),
                    '-o',str(out/'videoctrl.o'),str(out/'videoctrl.s')],check=True)
    subprocess.run([paths.VLINK,'-b','ataritos','-s','-o',str(out/'VIDCTRL.TOS'),'-M'+str(out/'VIDCTRL.MAP'),str(out/'videoctrl.o')],
                   check=True)
    manifest=dict(build=build_id,executable_sha256=sha(out/'VIDCTRL.TOS'),source_sha256=hashes,
                  shared_border_sha256=sha(paths.RT_INCLUDE/'borders.s'),
                  capture_sha256=sha(capture),capture_verification=verification,
                  phases=['closed','top only','top and bottom'],seconds_per_phase=20,
                  cpu='16 MHz, cache on throughout',stride=256,picture_guard_top=10,
                  scope='static scanout; no gameplay, no runtime Blitter',
                  kernel_changes='test-only register gates + NOP, d3 preserved, warm extra top word; delay counts unchanged')
    (out/'BUILD.JSN').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copy(ROOT/'tools/videoctrl.py',out/'videoctrl.py')
    for name in ['README.TXT','MESSAGE.TXT']:
        src=ROOT/'docs'/('megaste-video-control-'+name.lower())
        (out/name).write_bytes(src.read_text().replace('\n','\r\n').encode('ascii'))
    with zipfile.ZipFile(out/'SOURCE.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for name in sources+['vc_build.i','videoctrl.py','VIDCTRL.MAP']:
            z.write(out/name,name)
    names=['VIDCTRL.TOS','REFPIC.BMP','README.TXT','MESSAGE.TXT','BUILD.JSN','SOURCE.ZIP']
    (out/'SHA256.TXT').write_text(''.join(f'{sha(out/name)}  {name}\n' for name in names))
    with zipfile.ZipFile(out/'VIDCTRL.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for name in names+['SHA256.TXT']:
            z.write(out/name,'VIDCTRL/'+name)
    print(out/'VIDCTRL.ZIP',build_id,sha(out/'VIDCTRL.TOS'))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=ROOT/'build/megaste-video-control')
    args=ap.parse_args()
    build(args.out.resolve(),args.capture.resolve())
