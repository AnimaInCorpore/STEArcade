#!/usr/bin/env python3
"""Verify the CIRCLE.PRG package entry point, real keys and scanout in Hatari."""
import argparse
import json
import os
from pathlib import Path
import re
from statistics import median
import subprocess
import time

import numpy as np
from PIL import Image

import circle
from videoctrl_test import HATARI, TOS


def check(out):
    work = out/'verify'
    work.mkdir(exist_ok=True)
    exe = work/'CIRCLE.PRG'
    exe.write_bytes((out/exe.name).read_bytes())
    for path in (work/'CIRC00.TXT', work/'commands.fifo', work/'trace.log',
                 work/'both.png', work/'top.png', work/'closed.png'):
        path.unlink(missing_ok=True)
    fifo = work/'commands.fifo'
    trace = work/'trace.log'
    log = work/'CIRC00.TXT'
    cmd = [str(HATARI), '--machine', 'megaste', '--memsize', '4', '--tos', str(TOS),
           '--fast-boot', 'true', '--cpu-exact', 'true', '--compatible', 'true',
           '--fast-forward', 'false', '--confirm-quit', 'off', '--sound', 'off',
           '--cmd-fifo', str(fifo), '--trace', 'video_sync,io_write',
           '--trace-file', str(trace), str(exe)]

    def send(line):
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (line + '\n').encode())
        finally:
            os.close(fd)

    def wait_for(path, needle):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise RuntimeError(f'Hatari exited. See {work / "host.log"}')
            if path.exists() and needle in path.read_bytes():
                return
            time.sleep(.025)
        raise TimeoutError(path)

    def tap(code):
        send(f'hatari-event keydown 0x{code:02x}')
        time.sleep(.08)
        send(f'hatari-event keyup 0x{code:02x}')
        time.sleep(.18)

    def shot(name):
        path = work/(name + '.png')
        send(f'hatari-debug screenshot {path}')
        wait_for(path, b'IEND\xaeB`\x82')

    phase = re.compile(r'sync=(0x\w+) video_cyc_w=(\d+)')
    def timings():
        # Capture just the settled frames, ignoring key dispatch frames.
        offset = trace.stat().st_size
        time.sleep(.35)
        with trace.open() as stream:
            stream.seek(offset)
            raw = [(int(m[1], 16), int(m[2])/2) for m in phase.finditer(stream.read())]
        result = {}
        for label, line in [('top',33), ('bottom',262)]:
            pulses = [(a % 512, b-a) for (mode,a),(after,b) in zip(raw,raw[1:])
                      if mode == 0 and after == 2 and int(a//512) == line and 20 < b-a < 180]
            if pulses:
                result[label] = [median(v) for v in zip(*pulses)]
        return result

    profiles = {}
    with (work/'host.log').open('w') as host:
        proc = subprocess.Popen(cmd, stdout=host, stderr=host,
                                env=os.environ | {'SDL_VIDEO_DRIVER':'dummy', 'SDL_AUDIO_DRIVER':'dummy'})
        try:
            wait_for(log, b'CIRCLE 1')
            time.sleep(.8)
            shot('both')
            profiles['default'] = timings()
            for key in range(1, 9):
                tap(key + 1)
                profiles[str(key)] = timings()
            tap(0x0a)
            shot('top')
            profiles['top'] = timings()
            tap(0x0a)
            shot('closed')
            profiles['closed'] = timings()
            tap(0x0b)
            profiles['reset'] = timings()
            tap(0x2e)
            tap(0x2d)
            tap(0x13)
            wait_for(log, b'DONE interactive session: 00000001')
        finally:
            proc.terminate()
            proc.wait(timeout=5)

    text = log.read_text()
    events = [[int(v,16) for v in m.split()] for m in re.findall(r'^EVENT (.*)', text, re.M)]
    state = [e[1:] for e in events]
    assert state == [
        [255,0,78,8,101,17], [2,0,77,8,101,17], [3,0,78,8,101,17],
        [4,0,78,8,100,17], [5,0,78,8,101,17], [6,0,78,8,101,16],
        [7,0,78,8,101,17], [8,0,78,7,101,17], [9,0,78,8,101,17],
        [10,1,78,8,101,17], [10,2,78,8,101,17], [11,0,78,8,101,17],
        [46,0,78,8,101,17], [45,1,78,8,101,17],
    ], state
    assert all(a[0] < b[0] for a,b in zip(events, events[1:]))
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in text
    stages = [int(n, 16) for n in re.search(r'^STAGE (.*)', text, re.M)[1].split()]
    assert stages[2] == stages[7] == stages[16] == 0, stages
    controls = [int(m,16)&3 for m in re.findall(r'IO write.b \$ffff8e21 = \$([0-9a-fA-F]+)', trace.read_text())]
    assert controls == [3,0], controls
    assert profiles['top'].keys() == {'top'} and not profiles['closed'], profiles
    for k in ('default','2','4','6','8','reset'):
        assert profiles[k].keys() == {'top','bottom'}, profiles
    for key, border, axis in [('1','top',0),('3','bottom',0),('5','bottom',1),('7','top',1)]:
        assert abs(profiles[key][border][axis] - profiles['default'][border][axis] + 5) <= 2, profiles
        other = 'top' if border == 'bottom' else 'bottom'
        assert all(abs(a-b)<=2 for a,b in zip(profiles[key][other],profiles['default'][other])), profiles

    card = np.asarray(Image.open(out/'REFPIC.BMP').convert('RGB'))
    for name, y, height in [('both',0,276),('top',0,229),('closed',58,200)]:
        shot_data = np.asarray(Image.open(work/(name+'.png')).convert('RGB'))
        want = card[:height].repeat(2,0).repeat(2,1)
        crop = shot_data[y:y+height*2,96:736]
        assert crop.shape == want.shape, (name,crop.shape)
        # The left HUD area holds live numbers. Compare every other picture pixel.
        diff = np.any(want != crop, axis=2)
        diff[64:128,:96] = False
        assert not np.any(diff), (name, int(np.count_nonzero(diff)))
    result = dict(executable_sha256=circle.vc.sha(exe), hatari_sha256=circle.vc.sha(HATARI),
                  cpu_writes=controls, events=events, median_pulses=profiles,
                  scanout_rows={'both':276,'top':229,'closed':200}, restoration=True)
    (work/'RESULT.JSN').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=circle.ROOT/'build/megaste-circle')
    check(parser.parse_args().out.resolve())
