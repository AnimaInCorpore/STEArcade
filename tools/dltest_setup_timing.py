#!/usr/bin/env python3
"""Run only DLTEST's original setup kernels in Hatari and save aggregate timing.

Example: venv/bin/python tools/dltest_setup_timing.py --hatari /path/to/hatari
These are CPU-plus-Blitter elapsed times, not isolated register setup cycles.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import dltest


def parse(report):
    rows = []
    chunks = re.split(r'BEGIN mode \(0=8MHz,1=16MHz,2=16MHz/cache\): ', report)
    for chunk in chunks[1:]:
        mode = int(chunk[:8], 16)
        for match in re.findall(
            r'SETUP kind/postStartNOPs/elapsed200HzTicks/badwords: '
            r'([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]+)', chunk
        ):
            kind, nops, ticks, badwords = (int(v, 16) for v in match)
            rows.append(dict(mode=mode, kind=kind, nops=nops, ticks=ticks,
                             seconds=ticks / 200, badwords=badwords))
    assert len(rows) == 30, ('incomplete Mega STE setup run', len(rows))
    assert {(r['mode'], r['kind'], r['nops']) for r in rows} == {
        (m, k, n) for m in range(3) for k in range(2) for n in [0, 1, 2, 4, 8]}
    assert all(r['badwords'] == 0 for r in rows), rows
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--hatari', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--hardware', type=Path, help='returned DLTEST.TXT to compare')
    args = ap.parse_args()
    work = args.out.resolve()
    dltest.build(work, quick=True)
    executable = work / 'DLTEST.TOS'
    subprocess.run([
        dltest.paths.VASM, '-m68000', '-Ftos', '-quiet', '-nowarn=2047',
        '-DQUICK=1', '-DSETUP_ONLY=1',
        '-I' + str(dltest.paths.RT_INCLUDE), '-I' + str(work),
        '-I' + str(dltest.ROOT / 'tools'), '-o', str(executable),
        str(dltest.ROOT / 'tools/dltest.s')], check=True)
    result = work / 'DLTEST.TXT'
    result.unlink(missing_ok=True)
    tos = Path(os.environ.get('TOS',
        '/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img'))
    cmd = [str(args.hatari.resolve()), '--machine', 'megaste', '--memsize', '4',
           '--tos', str(tos), '--fast-boot', 'true', '--fast-forward', 'true',
           '--cpu-exact', 'true', '--compatible', 'true', '--sound', 'off',
           '--confirm-quit', 'off', '--log-file', str(work / 'hatari.log'),
           str(executable)]
    with (work / 'host.log').open('w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                report = result.read_text(errors='replace') if result.exists() else ''
                if 'FATAL unexpected' in report:
                    raise RuntimeError(report[-2500:])
                if 'DONE -' in report:
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f'Hatari exited; see {work}')
                time.sleep(.1)
            else:
                raise RuntimeError(f'timing run timeout; see {work}')
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
    rows = parse(report)
    data = dict(command=cmd, timings=rows,
                hatari_sha256=hashlib.sha256(args.hatari.read_bytes()).hexdigest(),
                tos_sha256=hashlib.sha256(tos.read_bytes()).hexdigest(),
                executable_sha256=dltest.sha(executable),
                kernel_source_sha256=dltest.sha(dltest.ROOT / 'tools/dltest_setup.s'))
    if args.hardware:
        hardware = parse(args.hardware.read_text(errors='replace'))
        data['hardware_report_sha256'] = dltest.sha(args.hardware)
        data['hardware_timings'] = hardware
        data['tick_differences_from_hardware'] = [
            row['ticks'] - hw['ticks'] for row, hw in zip(rows, hardware)]
    (work / 'setup-timing.json').write_text(json.dumps(data, indent=2) + '\n')
    for row in rows:
        print(f"mode {row['mode']} kind {row['kind']} NOPs {row['nops']}: "
              f"{row['ticks']} ticks ({row['seconds']:.3f}s), zero bad words")


if __name__ == '__main__':
    main()
