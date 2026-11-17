#!/usr/bin/env python3
"""Exercise the shipped probe using real Hatari key events and video traces."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

from PIL import Image
import numpy as np

import pulseprobe as probe
from videoctrl_test import HATARI, TOS


def check(out):
    work = out / 'verify'
    work.mkdir(exist_ok=True)
    for path in work.glob('PULSE*.TXT'):
        path.unlink()
    fifo = work / 'commands.fifo'
    fifo.unlink(missing_ok=True)
    exe = work / 'PULSE.TOS'
    shutil.copyfile(out / exe.name, exe)
    syms = {m[2]: int(m[1], 16) for m in
            re.finditer(r'0x([0-9a-f]+) (\w+):', (out / 'PULSE.MAP').read_text())}
    offset = syms['ip_state']
    state = work / 'state.bin'
    cmd = [str(HATARI), '--machine', 'megaste', '--memsize', '4', '--tos', str(TOS),
           '--cpu-exact', 'true', '--compatible', 'true', '--fast-boot', 'true',
           '--fast-forward', 'false', '--sound', 'off', '--confirm-quit', 'off',
           '--cmd-fifo', str(fifo), '--trace', 'video_sync,io_write',
           '--trace-file', str(work / 'trace.log'), str(exe)]

    def send(line):
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (line + '\n').encode())
        finally:
            os.close(fd)

    def await_file(path, predicate, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise RuntimeError(f'Hatari exited, see {work / "host.log"}')
            if path.exists():
                data = path.read_bytes()
                if predicate(data):
                    return data
            time.sleep(.025)
        raise TimeoutError(path)

    def get_state():
        state.unlink(missing_ok=True)
        send(f"hatari-debug savebin {state} 'TEXT+${offset:x}' 6")
        return struct.unpack('>3H', await_file(state, lambda data: len(data) == 6, 3))

    def wait_state(mode, trials, seconds=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            got, _, count = get_state()
            if (got, count) == (mode, trials):
                return
        raise AssertionError((mode, trials, get_state()))

    def tap(code, hold=.085):
        send(f'hatari-event keydown 0x{code:02x}')
        time.sleep(hold)
        send(f'hatari-event keyup 0x{code:02x}')
        time.sleep(.085)

    def screenshot(name):
        image = work / (name + '.png')
        image.unlink(missing_ok=True)
        send(f'hatari-debug screenshot {image}')
        await_file(image, lambda data: data.endswith(b'IEND\xaeB`\x82'))

    def run(index):
        nonlocal proc
        log = work / f'PULSE{index:02}.TXT'
        with (work / 'host.log').open('a') as host:
            proc = subprocess.Popen(cmd, stdout=host, stderr=host,
                                    env=os.environ | {'SDL_VIDEO_DRIVER': 'dummy', 'SDL_AUDIO_DRIVER': 'dummy'})
            try:
                await_file(log, lambda data: b'PULSE 1' in data)
                time.sleep(.7)
                wait_state(0, 0)
                # Firing before the operator confirms a clean baseline must do nothing.
                tap(0x39)
                wait_state(0, 0)
                tap(0x2e)
                wait_state(1, 0)
                if index == 1:
                    tap(0x01)
                elif index == 2:
                    tap(0x19)  # P switches to the adjustable reference
                    tap(0x4d)
                    tap(0x50)
                    tap(0x39)
                    wait_state(4, 1)
                    tap(0x2e)
                    wait_state(1, 1)
                    tap(0x14)
                    wait_state(3, 2)
                    tap(0x2d)  # stop a live repeat and keep its actual pulse count
                    wait_state(5, 2)
                    tap(0x1f)
                else:
                    screenshot('top')
                    tap(0x39, .7)
                    wait_state(4, 1)
                    tap(0x2e)
                    wait_state(1, 1)
                    tap(0x4b)  # left -> delay 100, adjustable family
                    tap(0x48)  # up -> width 18
                    tap(0x14)  # repeat must be blocked after changing settings
                    wait_state(1, 1)
                    tap(0x39)
                    wait_state(4, 2)
                    tap(0x2e)
                    wait_state(1, 2)
                    tap(0x14)
                    wait_state(3, 3)
                    time.sleep(.4)
                    screenshot('both')
                    wait_state(4, 3, seconds=15)
                    tap(0x2d)
                    wait_state(5, 3)
                    tap(0x39)
                    wait_state(5, 3)
                    tap(0x13)
                return await_file(log, lambda data: b'DONE interactive session' in data).decode()
            finally:
                proc.terminate()
                proc.wait(timeout=5)
    proc = None
    text = run(0)
    trace = (work / 'trace.log').read_text()
    controls = [int(v, 16) & 3 for v in re.findall(r'IO write.b \$ffff8e21 = \$([0-9a-fA-F]+)', trace)]
    assert controls[-2:] == [3, 0], controls
    assert controls[:-2] in ([], [0]), controls
    assert not re.search(r'IO write.[bw] \$ffff8a3c', trace)
    # A low-frequency write on line 262 can only come from an active bottom pulse.
    bottom_count = sum(1 for cyc in re.findall(r'sync=0x00 video_cyc_w=(\d+)', trace)
                       if int(cyc) // 1024 == 262)
    assert bottom_count == 502, bottom_count
    trials = [[int(v, 16) for v in line.split()] for line in re.findall(r'^TRIAL (.*)', text, re.M)]
    assert [r[:5] for r in trials] == [[1, 0, 101, 17, 1], [2, 1, 100, 18, 1], [3, 1, 100, 18, 500]], trials
    assert [(r[6], r[7]) for r in trials] == [(1, 1), (1, 1), (500, 2)], trials
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in text, text
    source = np.asarray(Image.open(out / 'REFPIC.BMP').convert('RGB'))
    for name, rows in [('top', 219), ('both', 256)]:
        shot = np.asarray(Image.open(work / f'{name}.png').convert('RGB'))
        expected = source[:rows, 48:272].repeat(2, axis=0).repeat(2, axis=1)
        got = shot[20:20+rows*2, 192:640]
        assert np.array_equal(got, expected), (name, got.shape)
    # Relaunch into the same writable folder. Esc should write a fresh log.
    text2 = run(1)
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in text2
    assert (work / 'PULSE00.TXT').read_text().splitlines() == text.splitlines()
    assert not re.search(r'^TRIAL ', text2, re.M)
    partial = run(2)
    stopped = [[int(v, 16) for v in line.split()] for line in re.findall(r'^TRIAL (.*)', partial, re.M)]
    assert [r[:5] for r in stopped] == [[1, 1, 102, 16, 1], [2, 1, 102, 16, 500]], stopped
    assert 0 < stopped[1][6] < 500 and stopped[1][7] == 2, stopped
    partial_trace = (work / 'trace.log').read_text()
    partial_writes = sum(1 for cyc in re.findall(r'sync=0x00 video_cyc_w=(\d+)', partial_trace)
                         if int(cyc) // 1024 == 262)
    assert partial_writes == sum(r[6] for r in stopped), (partial_writes, stopped)
    assert 'Restoration register/vector mismatches (must be zero): 00000000' in partial
    result = dict(executable_sha256=probe.vc.sha(exe), hatari_sha256=probe.vc.sha(HATARI),
                  cpu_writes=controls, bottom_writes=bottom_count, trials=trials,
                  top_and_both_pixels_exact=True, clean_baseline_required=True,
                  repeat_requires_matching_single=True, corruption_lock=True,
                  numbered_logs=True, early_stop=stopped[1], restored_on_r_s_and_esc=True)
    (work / 'RESULT.JSN').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=probe.ROOT / 'build/megaste-pulse-probe')
    check(parser.parse_args().out.resolve())
