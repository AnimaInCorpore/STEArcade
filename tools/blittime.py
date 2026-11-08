#!/usr/bin/env python3
"""Build the focused, unattended Mega STE BLITTIME.TOS and analyse its report."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import paths

KINDS = ['destination writes', 'immediate destination RMW', 'fenced destination RMW',
         'word start including skew', 'HOG preload plus BSET start',
         'unshifted full copy', 'idle Blitter register writes', 'ordinary RAM writes']
FIELDS = 'mode policy repeat id kind rows nops passes mfp_counts tos_ticks vbls bad_words first_offset expected actual speed_before speed_after kernel_pc source_address destination_address'.split()


def cases():
    result = [(0, k, 4, n) for k in [0, 1] for n in [0, 1, 2, 4, 8]]
    result += [(1, k, y, n) for k in range(5) for y in [4, 8, 12] for n in [0, 2, 8]]
    result += [(1, 5, y, n) for y in [4, 8, 12] for n in [0, 8]]
    result += [(1, k, 4, n) for k in [6, 7] for n in [0, 8]]
    return result


def kernel(kind, nops):
    lines = [f'kernel_{kind}_{nops}:', '.batch:', '\tmove.l a0,(a1)']
    if kind in [1, 2]:
        lines += ['\tmove.l d0,(a2)']
    lines += ['\tmove.w #1023,d7', '.pass:']
    if kind not in [1, 2]:
        lines += ['\tmove.l d0,(a2)']
    lines += ['\tmove.w d1,(a3)']
    if kind == 3:
        lines += ['\tmove.w d2,(a4)']
    elif kind == 4:
        lines += ['\tmove.b #$40,(a4)', '\tbset #7,(a4)']
    else:
        lines += ['\tmove.b d2,(a4)']
    lines += ['\tnop'] * nops
    if kind == 2:
        lines += ['.wait:', '\tbtst #7,(a4)', '\tbne .wait']
    if kind in [1, 2]:
        lines += ['\tadd.w d4,2(a2)', '\texg d3,d4']
    else:
        lines += ['\teor.l #128,d0']
    lines += ['\tdbf d7,.pass', '\tdbf d5,.batch', '\trts']
    return '\n'.join(lines) + '\n'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out, quick=False):
    out.mkdir(parents=True, exist_ok=True)
    batches, repeats = (1, 1) if quick else (16, 2)
    profiles = cases()
    kernels = '\tsection text\n'
    kernels += ''.join(kernel(k, n) for k in range(8) for n in [0, 1, 2, 4, 8])
    kernels += '\tsection data\n\teven\ncases:\n'
    kernels += ''.join(f'\tdc.w {p},{k},{y},{n}\n\tdc.l kernel_{k}_{n}\n' for p, k, y, n in profiles)
    (out / 'btime_kernels.i').write_text(kernels)
    total = len(profiles) * repeats * 3
    (out / 'btime_total.i').write_text(f"\tdc.b '{total:03d}'\n")
    identity = hashlib.sha256((ROOT / 'tools/blittime.s').read_bytes() +
                             Path(__file__).read_bytes() + kernels.encode() +
                             f'{batches},{repeats}'.encode()).hexdigest()[:16]
    (out / 'btime_build.i').write_text(f"\tdc.b 'Build {identity}; batches {batches}; repeats {repeats}',13,10\n")
    cmd = [paths.VASM, '-m68000', '-Ftos', '-quiet', '-nowarn=2047',
           f'-DBATCHES={batches}', f'-DREPEATS={repeats}', f'-DCASE_COUNT={len(profiles)}',
           '-I' + str(out), '-o', str(out / 'BLITTIME.TOS'), str(ROOT / 'tools/blittime.s')]
    subprocess.run(cmd, check=True)
    meta = dict(version=1, build_id=identity, batches=batches, repeats=repeats,
                passes=batches * 1024, count=total, profiles=profiles, kinds=KINDS,
                source_sha256={p.name: sha(p) for p in [ROOT / 'tools/blittime.s', Path(__file__)]},
                executable_sha256=sha(out / 'BLITTIME.TOS'))
    (out / 'BUILD.JSN').write_text(json.dumps(meta, indent=2) + '\n')
    return meta


def clock_calibration(text):
    """Infer video rate: BLITTIME preserves the desktop display mode."""
    values = re.findall(r'CAL mode mfpCounts tosTicks vbls: ([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]+)', text)
    assert len(values) == 3, 'missing clock calibration'
    results = []
    for expected_mode, fields in enumerate(values):
        mode, counts, ticks, vbls = (int(v, 16) for v in fields)
        seconds = counts / 12288
        assert mode == expected_mode and .98 < seconds < 1.02, fields
        assert 200 <= ticks <= 202, fields
        rate = min([50, 60, 71], key=lambda hz: abs(vbls / seconds - hz))
        assert abs(vbls - seconds * rate) <= 2, fields
        results.append(dict(mode=mode, mfp_counts=counts, tos_ticks=ticks,
                            vbls=vbls, inferred_video_hz=rate))
    assert len({r['inferred_video_hz'] for r in results}) == 1, 'video rate changed between CPU modes'
    return results


def parse(path, meta):
    text = path.read_text(errors='replace')
    assert f"Build {meta['build_id']};" in text, 'report/build identity mismatch'
    rows = []
    for line in text.splitlines():
        if not re.match(r'^CASE [0-9A-F]{8} ', line):
            continue
        values = line.split()[1:]
        assert len(values) == len(FIELDS), line
        row = dict(zip(FIELDS, (int(v, 16) for v in values)))
        row['seconds'] = row['mfp_counts'] / 12288
        row['us_per_pass'] = row['seconds'] * 1e6 / row['passes']
        rows.append(row)
    expected = [(m, r, i) for m in range(3) for r in range(meta['repeats']) for i in range(len(meta['profiles']))]
    assert [(r['mode'], r['repeat'], r['id']) for r in rows] == expected, ('incomplete/duplicate/reordered report', len(rows), len(expected))
    for row in rows:
        assert [row[k] for k in ['policy', 'kind', 'rows', 'nops']] == list(meta['profiles'][row['id']]), row
        assert row['passes'] == meta['passes'], row
        assert row['mfp_counts'] > 0, row
        for key in ['speed_before', 'speed_after']:
            assert row[key] & 3 == [0, 2, 3][row['mode']], row
    clock_calibration(text)
    done = re.search(r'DONE - .*?Total bad words: ([0-9A-F]{8})', text)
    assert done and int(done[1], 16) == sum(r['bad_words'] for r in rows), 'missing/inconsistent final summary'
    return rows



def summary(data):
    rows = data['rows']
    groups = {}
    for r in rows:
        key = (r['mode'], r['policy'], r['kind'], r['rows'], r['nops'])
        groups.setdefault(key, []).append(r['us_per_pass'])
    def mean(m, p, k, y=4, n=0):
        return statistics.mean(groups[m, p, k, y, n])
    lines = ['BLITTIME analysis', 'Build ' + data['build_id'],
             f"Complete measurements: {len(rows)}; drawing checks: " +
             ('PASS' if data['all_drawing_checks_pass'] else 'FAIL'),
             'All times below are microseconds per pass; averages of repeats.',
             'Timing differences are observations, not automatic hardware failures.', '']
    if 'clock_calibration' in data:
        lines.insert(2, f"Inferred video rate: {data['clock_calibration'][0]['inferred_video_hz']} Hz")
    for m in range(3):
        lines += [f'Mode {m}:',
                  '  Normal/minimal interrupts, three writes: '
                  f'{mean(m,0,0):.4f} / {mean(m,1,0):.4f}',
                  '  Normal/minimal interrupts, immediate RMW: '
                  f'{mean(m,0,1):.4f} / {mean(m,1,1):.4f}',
                  '  Minimal IRQ masked payload 80/160/240 bus cycles: ' +
                  ' / '.join(f'{mean(m,1,0,y):.4f}' for y in [4,8,12]),
                  '  Incremental microseconds per bus cycle: '
                  f'{(mean(m,1,0,12)-mean(m,1,0,4))/160:.6f}',
                  '  Immediate RMW / fenced RMW: '
                  f'{mean(m,1,1):.4f} / {mean(m,1,2):.4f}',
                  '  Byte start / word start / HOG preload+BSET start: '
                  f'{mean(m,1,0):.4f} / {mean(m,1,3):.4f} / {mean(m,1,4):.4f}',
                  '  Idle Blitter register writes / ordinary RAM writes: '
                  f'{mean(m,1,6):.4f} / {mean(m,1,7):.4f}', '']
    max_repeat = max(max(v)-min(v) for v in groups.values())
    max_clock = max(abs(r['seconds']-r['tos_ticks']/200) for r in rows)
    lines += [f'Maximum repeat spread: {max_repeat:.5f} us/pass',
              f'Maximum MFP-vs-TOS elapsed difference: {max_clock:.6f} seconds',
              'BSET includes a HOG preload write; the fence includes polling.',
              'Those differences include changed instructions and ordering.',
              'For hardware attribution, compare matching build IDs and profile IDs.',
              'Full row data and any reference differences are in the JSON.']
    return '\n'.join(lines) + '\n'


def analyse(path, meta, out, reference=None):
    rows = parse(path, meta)
    data = dict(report_sha256=sha(path), build_id=meta['build_id'], rows=rows,
                clock_calibration=clock_calibration(path.read_text(errors='replace')),
                all_drawing_checks_pass=not any(r['bad_words'] for r in rows))
    # Preserve differences, including failed cases: never turn a timing probe's
    # drawing failure into a missing result or a timing success.
    if reference:
        refs = parse(reference, meta)
        data['reference_report_sha256'] = sha(reference)
        data['reference_clock_calibration'] = clock_calibration(reference.read_text(errors='replace'))
        data['differences_us_per_pass'] = [a['us_per_pass'] - b['us_per_pass'] for a, b in zip(rows, refs)]
    out.write_text(json.dumps(data, indent=2) + '\n')
    out.with_suffix('.TXT').write_text(summary(data))
    return data


def verify(out, meta, hatari):
    work = out / 'HATARI'
    work.mkdir(exist_ok=True)
    shutil.copyfile(out / 'BLITTIME.TOS', work / 'BLITTIME.TOS')
    report = work / 'BLITTIME.TXT'
    report.unlink(missing_ok=True)
    tos = Path(os.environ.get('TOS', '/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img'))
    cmd = [str(hatari), '--machine', 'megaste', '--memsize', '4', '--tos', str(tos),
           '--fast-boot', 'true', '--fast-forward', 'true', '--cpu-exact', 'true',
           '--compatible', 'true', '--sound', 'off', '--confirm-quit', 'off',
           '--log-file', str(work / 'hatari.log'), str(work / 'BLITTIME.TOS')]
    with (work / 'host.log').open('w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                text = report.read_text(errors='replace') if report.exists() else ''
                if 'DONE -' in text:
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f'Hatari exited early; see {work}')
                time.sleep(.1)
            else:
                raise RuntimeError(f'Hatari timeout; see {work}')
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
    data = analyse(report, meta, work / 'RESULT.JSN')
    data.update(hatari_sha256=sha(hatari), tos_sha256=sha(tos), command=cmd)
    (work / 'RESULT.JSN').write_text(json.dumps(data, indent=2) + '\n')
    assert data['all_drawing_checks_pass'], [(r['mode'], r['id'], r['bad_words']) for r in data['rows'] if r['bad_words']]
    # Independent clocks must agree to within timer quantisation and boundaries.
    for row in data['rows']:
        assert abs(row['seconds'] - row['tos_ticks'] / 200) < .015, row
        rate = data['clock_calibration'][row['mode']]['inferred_video_hz']
        assert abs(row['seconds'] - row['vbls'] / rate) < 2 / rate, row
    print(f"PASS: {len(data['rows'])} profiles, all private RAM guards and output words; both clocks agree")
    return data


def package(out, meta, candidate_reference=None):
    guide = (ROOT / 'docs/blittime-instructions.txt').read_text()
    (out / 'README.TXT').write_bytes(guide.replace('\n', '\r\n').encode('ascii'))
    with zipfile.ZipFile(out / 'SOURCE.ZIP', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ['blittime.s', 'blittime.py']:
            z.write(ROOT / 'tools' / name, name)
        for path in sorted(out.glob('*.i')):
            z.write(path, path.name)
    files = [out / name for name in ['BLITTIME.TOS', 'BUILD.JSN', 'README.TXT', 'SOURCE.ZIP']]
    if candidate_reference:
        candidate_rows = parse(candidate_reference, meta)
        assert not any(r['bad_words'] for r in candidate_rows), 'candidate reference has drawing failures'
        shutil.copyfile(candidate_reference, out / 'MMIOREF.TXT')
        files.append(out / 'MMIOREF.TXT')
    if (out / 'HATARI/BLITTIME.TXT').exists():
        shutil.copyfile(out / 'HATARI/BLITTIME.TXT', out / 'HATREF.TXT')
        files.append(out / 'HATREF.TXT')
    (out / 'SHA256.TXT').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
    with zipfile.ZipFile(out / 'BLITTIME.ZIP', 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files + [out / 'SHA256.TXT']:
            z.write(p, p.name)
    print(out / 'BLITTIME.ZIP')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT / 'build/blittime')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--quick', action='store_true', help='developer smoke test only: fewer passes/repeats')
    ap.add_argument('--hatari', type=Path, default=Path('/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari'))
    ap.add_argument('--report', type=Path, help='analyse returned BLITTIME.TXT with the selected BUILD.JSN')
    ap.add_argument('--reference', type=Path)
    ap.add_argument('--candidate-reference', type=Path, help='include a matching private-candidate report as MMIOREF.TXT')
    ap.add_argument('--package-only', action='store_true', help='package an already built/verified output folder')
    args = ap.parse_args()
    out = args.out.resolve()
    if args.package_only:
        meta = json.loads((out / 'BUILD.JSN').read_text())
        assert sha(out / 'BLITTIME.TOS') == meta['executable_sha256']
        assert meta['source_sha256'] == {p.name: sha(p) for p in [ROOT / 'tools/blittime.s', Path(__file__)]}, 'sources changed; rebuild before packaging'
        package(out, meta, args.candidate_reference)
        return
    if args.report:
        meta = json.loads((out / 'BUILD.JSN').read_text())
        data = analyse(args.report, meta, out / 'RETURN.JSN', args.reference)
        print(f"{len(data['rows'])} profiles; drawing checks {'PASS' if data['all_drawing_checks_pass'] else 'FAIL'}")
        return
    meta = build(out, args.quick)
    if args.verify:
        verify(out, meta, args.hatari.resolve())
    package(out, meta, args.candidate_reference)


if __name__ == '__main__':
    main()
