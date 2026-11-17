#!/usr/bin/env python3
"""Build the keyboard-controlled Mega STE pulse probe and its source ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import numpy as np
from PIL import Image

import bottomprobe as bp
import videoctrl as vc

ROOT = vc.ROOT
SOURCES = ['pulseprobe.s', 'pulseprobe.i', 'videoctrl.s', 'bottomprobe.i',
           'ikbd.s', 'vc_borders.i', 'bp_phases.i', 'FRAME.BIN', 'PALETTE.BIN',
           'LABELS.BIN', 'TIMERS.BIN', 'IPLABEL.BIN', 'IPDELAY.BIN', 'IPWIDTH.BIN']
PALETTE = [0x000, 0xfff, 0x700, 0x070, 0x007, 0x770, 0x077, 0x707,
           0x333, 0x555, 0x733, 0x373, 0x337, 0xf72, 0x27f, 0x2f7]


def chart():
    """Original alignment chart with fine detail and a distinct bottom band."""
    frame = np.zeros((320, 512), dtype=np.uint8)
    y, x = np.indices((256, 224))
    cells = 1 + (x // 16 + (y // 16) * 3) % 15
    checker = ((x // (1 + (y // 32) % 4) + y // 2) & 1).astype(bool)
    image = np.where(checker, cells, 0).astype(np.uint8)
    image[:, ::16] = 1
    image[::16] = 1
    for col in range(0, 224, 16):
        image[222:256, col:col + 16] = 1 + col // 16
        image[222:256, col] = 0
    image[222] = image[255] = 1
    frame[10:266, 48:272] = image
    return frame


def kernel():
    base = bp.kernel()
    anchor = '\tbd_check_late bd_late_low\n\tif BD_PALETTE'
    assert base.count(anchor) == 1
    # Count the actual executed gate after the pulse and Timer-A arm.
    hook = r'''
	tst.w low_gate
	bne.s .ip_count_done\@
	addq.l #1,ip_pulses
.ip_count_done\@:
'''
    return base.replace(anchor, '\tbd_check_late bd_late_low\n' + hook + '\tif BD_PALETTE')


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    frame = chart()
    (out / 'FRAME.BIN').write_bytes(vc.planar(frame))
    (out / 'PALETTE.BIN').write_bytes(np.array(PALETTE, dtype='>u2').tobytes())
    rgb = np.array([[17 * (((v >> n) & 7) * 2 + ((v >> (n + 3)) & 1))
                     for n in (8, 4, 0)] for v in PALETTE], dtype=np.uint8)
    Image.fromarray(rgb[frame[10:266, :320]]).save(out / 'REFPIC.BMP')
    extra = {
        'D': ['11110','10001','10001','10001','10001','10001','11110'],
        'Q': ['01110','10001','10001','10001','10101','10010','01101'],
        'R': ['11110','10001','10001','11110','10100','10010','10001'],
        'U': ['10001','10001','10001','10001','10001','10001','01110'],
        'W': ['10001','10001','10001','10101','10101','10101','01010'],
        'X': ['10001','10001','01010','00100','01010','10001','10001'],
        'F': ['11111','10000','10000','11110','10000','10000','10000'],
        'I': ['01110','00100','00100','00100','00100','00100','01110'],
    }
    vc.FONT.update(extra)
    tiles = {
        'IPLABEL.BIN': [p + status for p in ('', 'P01 ') for status in
                        (('C START','TOP','ONE','REPEAT','C OR X','R QUIT','FULL') if not p else
                         ('C','TOP','ONE','REP','C/X','QUIT','FULL'))],
        'IPDELAY.BIN': [f'D{n}' for n in range(97, 106)],
        'IPWIDTH.BIN': [f'W{n}' for n in range(13, 22)],
        'TIMERS.BIN': [''] + [f'{n:02} SEC' for n in range(1, 11)],
    }
    # Use explicit text for the legacy preset as well as the other modes.
    tiles['IPLABEL.BIN'][11] = 'P01 C X'
    for name, labels in tiles.items():
        (out / name).write_bytes(b''.join(vc.tile([label], 1) for label in labels))
    (out / 'LABELS.BIN').write_bytes(bytes(24 * 24))
    (out / 'bp_phases.i').write_text('\tdc.w 0,2,0,101,17,0\n')
    (out / 'vc_borders.i').write_text(kernel())
    for name in ('pulseprobe.s', 'pulseprobe.i', 'videoctrl.s', 'bottomprobe.i'):
        shutil.copy(ROOT / 'tools' / name, out / name)
    shutil.copy(vc.paths.RT_INCLUDE / 'ikbd.s', out / 'ikbd.s')
    hashes = {name: vc.sha(out / name) for name in SOURCES}
    build_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    (out / 'vc_build.i').write_text(f"\tdc.b 'Build {build_id}',13,10\n")
    subprocess.run([vc.paths.VASM, '-m68000', '-Fvobj', '-quiet', '-nowarn=2047',
                    '-I.', '-o', 'pulse.o', 'pulseprobe.s'], cwd=out, check=True)
    subprocess.run([vc.paths.VLINK, '-b', 'ataritos', '-s', '-o', 'PULSE.TOS',
                    '-MPULSE.MAP', 'pulse.o'], cwd=out, check=True)
    manifest = dict(build=build_id, executable_sha256=vc.sha(out / 'PULSE.TOS'),
                    sources=hashes, cpu='16 MHz/cache on',
                    start_dbf=[97, 105], width_dbf=[13, 21], repeat_vbls=500,
                    preset='P01 legacy, width DBF 17', picture='original alignment chart')
    (out / 'BUILD.JSN').write_text(json.dumps(manifest, indent=2) + '\n')
    for dest, src in [('README.TXT', 'readme'), ('MESSAGE.TXT', 'message')]:
        text = (ROOT / 'docs' / f'megaste-pulse-probe-{src}.txt').read_text()
        (out / dest).write_bytes(text.replace('\n', '\r\n').encode('ascii'))
    with zipfile.ZipFile(out / 'SOURCE.ZIP', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in SOURCES + ['vc_build.i', 'PULSE.MAP']:
            z.write(out / name, name)
    names = ['PULSE.TOS', 'REFPIC.BMP', 'README.TXT', 'MESSAGE.TXT', 'BUILD.JSN', 'SOURCE.ZIP']
    (out / 'SHA256.TXT').write_bytes(''.join(f'{vc.sha(out / n)}  {n}\r\n' for n in names).encode('ascii'))
    with zipfile.ZipFile(out / 'PULSE.ZIP', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in names + ['SHA256.TXT']:
            z.write(out / name, 'PULSE/' + name)
    print(out / 'PULSE.ZIP', build_id, manifest['executable_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/megaste-pulse-probe')
    build(parser.parse_args().out.resolve())
