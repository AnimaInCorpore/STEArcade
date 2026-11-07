#!/usr/bin/env python3
"""Build/package the unattended Mega STE diagnostic; --verify runs pinned Hatari."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import paths
from dltest_vectors import generate, scene_generate


def build(out, quick=False):
    out.mkdir(parents=True, exist_ok=True)
    generate(out)
    scene_generate(out)
    ikbd = (paths.RT_INCLUDE / 'ikbd.s').read_text()
    tap = '\tmove.b\t$fffffc02.w,d1'
    assert ikbd.count(tap) == 1
    (out / 'dltest_ikbd.i').write_text(ikbd.replace(tap, tap + '\n\tbsr input_observer'))
    borders=(paths.RT_INCLUDE/'borders.s').read_text()
    hook='\tbd_check_late bd_late_off'
    assert borders.count(hook)==1
    (out/'dltest_borders.i').write_text(borders.replace(hook,hook+'\n\tbsr border_off_sample'))
    for name, source in [('DLTEST', 'dltest'), ('MSTEDIAG', 'mstediag')]:
        cmd = [paths.VASM, '-m68000', '-Ftos', '-quiet', '-nowarn=2047',
               '-I' + str(paths.RT_INCLUDE), '-I' + str(out), '-I' + str(ROOT / 'tools'),
               '-o', str(out / (name + '.TOS'))]
        if quick:
            cmd += ['-DQUICK=1']
        subprocess.run(cmd + [str(ROOT / 'tools' / (source + '.s'))], check=True)


def verify_report(text, machine, inputs=True):
    modes = 3 if machine == 'megaste' else 1
    zero_tests = {
        'SCENE frame/badwords: [0-9A-F]+ ([0-9A-F]+)': 32*modes,
        'CPU 1024 SMC \\+64 MULU \\+64 DIVU mismatches: ([0-9A-F]+)': modes,
        'RAM EXTENDED total mismatches: ([0-9A-F]+)': modes,
        'PALETTE readback mismatches: ([0-9A-F]+)': modes,
        'RAW concurrent short-HOG destination badwords: ([0-9A-F]+)': modes,
        'SETUP kind/postStartNOPs/elapsed200HzTicks/badwords: [0-9A-F]+ [0-9A-F]+ [0-9A-F]+ ([0-9A-F]+)': 10*modes,
        'MATRIX profile/place/cases/badwords/MMIOwrites/passes/MFPticks: [0-9A-F]+ [0-9A-F]+ [0-9A-F]+ ([0-9A-F]+)': 24*modes,
        'FILE error\\(0=OK\\)/badlongs: ([0-9A-F]+) [0-9A-F]+': modes,
        'FILE error\\(0=OK\\)/badlongs: [0-9A-F]+ ([0-9A-F]+)': modes,
        'CAPTURE file/error\\(0=OK\\): [A-Z0-9.]+ ([0-9A-F]{8}) ': 3*modes,
    }
    for pattern, count in zero_tests.items():
        values = re.findall(pattern, text)
        assert len(values) == count, (pattern, len(values), count, text[-2000:])
        assert all(int(v, 16) == 0 for v in values), (pattern, values)
    assert text.count('RAM mismatched words: 00000000 ') == modes, text[-2000:]
    assert text.count('Blitter mismatched words: 00000000 ') == modes, text[-2000:]
    assert text.count('ILLEGAL caught (expected 1): 00000001 ') == modes, text[-2000:]
    assert text.count('IKBD transmit timeouts: 00000000 ') == modes, text[-2000:]
    border_flags=re.findall(r'BORDERS opening confirmed \(1=yes,0=no\): ([0-9A-F]+)',text)
    assert len(border_flags)==modes, text[-2000:]
    if machine=='megaste':
        assert border_flags[-1]=='00000001',text[-2000:]
        samples=re.findall(r'BORDERS post-picture samples / missing frames after warmup: ([0-9A-F]+) ([0-9A-F]+)',text)
        assert int(samples[-1][1],16)==0,text[-2000:]
    border_failures=sum(int(v,16)==0 for v in border_flags)
    assert f'SUMMARY automatic failure groups: {border_failures:08X} ' in text, text[-2000:]
    assert text.count('BEGIN OPEN BORDERS') == modes, text[-2000:]
    wanted = ['00000000', '00000002', '00000003'] if modes == 3 else ['00000000']
    for pattern in [r'FF8E21 readback \(STE=0\): ([0-9A-F]+)',
                    r'MODE end FF8E21 readback \(STE=0\): ([0-9A-F]+)']:
        assert re.findall("^"+pattern, text, re.M) == wanted, (pattern, text[-2000:])
    for ticks, vbls in re.findall(r'Raw phase elapsed 200Hz ticks / VBLs: ([0-9A-F]+) ([0-9A-F]+)', text):
        assert 600 <= int(ticks, 16) <= 605 and 148 <= int(vbls, 16) <= 153, (ticks, vbls)
    keys = 'Scancodes seen: ' + ''.join(f'{key:08X} ' for key in
        [0x02, 0x06, 0x1d, 0x39, 0x44, 0x48, 0x4b, 0x4d, 0x50])
    if inputs:
        assert text.count(keys) == 2*modes, text[-2000:]
        assert keys.replace('0000001D ', '').replace('00000044 ', '') in text.split('BEGIN mode')[0], text[:1000]
    else:
        assert 'Raw key events: 00000000 ' in text, text[-2000:]
        assert text.count('KEYBOARD status: NOT EXERCISED (unattended run).') == modes, text[-2000:]
    return modes


def verify(out, machines, inputs):
    hatari = os.environ.get('HATARI', '/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari')
    tos = os.environ.get('TOS', '/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img')
    for machine in machines:
        work = out / (machine if inputs else machine + '-quiet')
        build(work, quick=True)
        for old in list(work.glob('*.BMP')) + [work/'DLTEST.TXT', work/'DLIO.TMP']:
            old.unlink(missing_ok=True)
        fifo = work / 'commands.fifo'
        fifo.unlink(missing_ok=True)
        log = (work / 'host.log').open('w')
        proc = subprocess.Popen([hatari, '--machine', machine, '--memsize', '4', '--tos', tos,
            '--fast-boot', 'true', '--cpu-exact', 'true', '--compatible', 'true',
            '--sound', 'off', '--confirm-quit', 'off', '--cmd-fifo', str(fifo),
            '--log-file', str(work/'hatari.log'), str(work/'DLTEST.TOS')], stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+900
            last_control = 0
            stage = ''
            captures = set()
            border_count = 0
            border_started = 0
            while time.monotonic() < deadline:
                result = work/'DLTEST.TXT'
                text = result.read_text(errors='replace') if result.exists() else ''
                if 'FATAL unexpected' in text:
                    raise RuntimeError(f'{machine}: unexpected guest exception; see {result}')
                if 'DONE -' in text:
                    break
                stages = re.findall(r'^BEGIN .*$', text, re.M)
                if stages and stages[-1] != stage:
                    stage = stages[-1]
                    print(f'{machine}: {stage}', flush=True)
                count = text.count('BEGIN OPEN BORDERS')
                if count != border_count:
                    border_count, border_started = count, time.monotonic()
                if proc.poll() is not None:
                    raise RuntimeError(f'{machine}: Hatari exited; see {work}')
                if fifo.exists() and time.monotonic()-last_control > .3:
                    commands = []
                    if inputs and stage in ['BEGIN BIOS keyboard phase','BEGIN raw input / visual observation']:
                        commands += [f'hatari-event keypress {key:#x}' for key in
                            [0x02, 0x06, 0x1d, 0x39, 0x48, 0x4b, 0x4d, 0x50]]
                        if stage=='BEGIN raw input / visual observation':
                            commands.append('hatari-event keypress 0x44')
                    if count and time.monotonic()-border_started > .7 and ('open', count) not in captures:
                        commands.append(f'hatari-debug screenshot {work/f"open{count-1}.png"}')
                        captures.add(('open', count))
                    for mode in range(3):
                        if (work/f'BOBS{mode}.BMP').exists() and ('bobs', mode) not in captures:
                            commands.append(f'hatari-debug screenshot {work/f"bobs{mode}.png"}')
                            captures.add(('bobs', mode))
                    if commands:
                        with fifo.open('w') as f:
                            f.write('\n'.join(commands)+'\n')
                    last_control = time.monotonic()
                time.sleep(.1)
            else:
                raise RuntimeError(f'{machine}: timed out; see {work}')
            modes = verify_report(text, machine, inputs)
            for mode in range(modes):
                assert (work/f'BOBS{mode}.BMP').read_bytes() == (work/'REFERENCE/CPU31.BMP').read_bytes(), f'{machine}: bob BMP mismatch, mode {mode}'
                assert (work/f'OPEN{mode}.BMP').read_bytes() == (work/'REFERENCE/OPENCPU.BMP').read_bytes(), f'{machine}: border BMP mismatch, mode {mode}'
            print(f'{machine}: CPU/RAM/file/Blitter/scene/BMP checks PASS ({modes} modes, inputs={inputs}); border opening flags: '+str(re.findall(r'BORDERS opening confirmed \(1=yes,0=no\): ([0-9A-F]+)',text)),flush=True)
            # Only successful runs become shared reference material.
            for mode, label in enumerate(['8', '16', '16C'][:modes]):
                if machine == 'megaste':
                    shutil.copyfile(work/f'BOBS{mode}.BMP', out/f'REFERENCE/HAT{label}.BMP')
                    shutil.copyfile(work/f'OPEN{mode}.BMP', out/f'REFERENCE/HATO{label}.BMP')
                    if (work/f'open{mode}.png').exists():
                        shutil.copyfile(work/f'open{mode}.png', out/f'REFERENCE/OPEN{label}.PNG')
            if fifo.exists():
                with fifo.open('w') as f:
                    f.write(f'hatari-debug screenshot {work/"desktop.png"}\n')
                time.sleep(1)
            (work/'verification.json').write_text(json.dumps(dict(machine=machine,inputs=inputs,modes=modes,
                hatari_sha256=sha(Path(hatari)),tos_sha256=sha(Path(tos)),tos_binary_sha256=sha(work/'DLTEST.TOS'),
                native_report_sha256=sha(result),cpu_reference_match=True,border_opening_confirmed=re.findall(r'BORDERS opening confirmed \(1=yes,0=no\): ([0-9A-F]+)',text)),indent=2)+'\n')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            log.close()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(out):
    (out/'README.TXT').write_bytes((ROOT/'docs/megaste-instructions.txt').read_text().replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    shutil.copyfile(ROOT/'tools/dltest_compare.py',out/'COMPARE.PY')
    shutil.copyfile(out/'blit_cases.json',out/'BLITCASE.JSN')
    shutil.copyfile(out/'scene_cases.json',out/'SCENES.JSN')
    sources = list((ROOT/'tools').glob('dltest*.s')) + list((ROOT/'tools').glob('dltest*.py'))
    sources += [paths.RT_INCLUDE/'borders.s', paths.RT_INCLUDE/'ikbd.s', paths.RT_INCLUDE/'jagpad.s',
                ROOT/'engine/sprite_programs.py', ROOT/'engine/paths.py', ROOT/'tools/mstediag.s']
    metadata = dict(version=4,source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(sources)},
                    released_tos_binary_sha256=sha(out/'DLTEST.TOS'),fixture_count=1308,scene_frames=32,
                    verifies=[json.loads(p.read_text()) for p in sorted(out.glob('*/verification.json'))])
    (out/'BUILD.JSN').write_text(json.dumps(metadata,indent=2)+'\n')
    shutil.copyfile(ROOT/'LICENSE',out/'LICENSE.TXT')
    with zipfile.ZipFile(out/'SOURCE.ZIP','w',zipfile.ZIP_DEFLATED) as source_archive:
        for source in sources+[ROOT/'LICENSE',ROOT/'docs/megaste-diagnostic.md',ROOT/'docs/megaste-instructions.txt',ROOT/'docs/megaste-border-timing.md']:
            source_archive.write(source,source.relative_to(ROOT))
    timing_path=ROOT/'build/border-timing/long-cache/timing.json'
    timing_output=None
    if timing_path.exists():
        timing_data=dict(cache_on=json.loads(timing_path.read_text()))
        game_path=ROOT/'build/border-timing/timeplt-game/verified.json'
        if game_path.exists():timing_data['time_pilot']=json.loads(game_path.read_text())
        timing_output=out/'TIMING.JSN'
        timing_output.write_text(json.dumps(timing_data,indent=2)+'\n')
    files = [out/name for name in ['DLTEST.TOS','MSTEDIAG.TOS','README.TXT','COMPARE.PY','BLITCASE.JSN','SCENES.JSN','BUILD.JSN','LICENSE.TXT','SOURCE.ZIP']]
    if timing_output:files.append(timing_output)
    (out/'REF').mkdir(exist_ok=True)
    for reference in sorted((out/'REFERENCE').glob('*')):
        dest=out/'REF'/reference.name
        shutil.copyfile(reference,dest)
        files.append(dest)
    (out/'SHA256.TXT').write_text(''.join(sha(p)+'  '+str(p.relative_to(out))+'\n' for p in files))
    with zipfile.ZipFile(out/'DARKLORD.ZIP','w',zipfile.ZIP_DEFLATED) as archive:
        for path in files+[out/'SHA256.TXT']:
            archive.write(path,path.relative_to(out))
    print(out/'DARKLORD.ZIP',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/dltest')
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--verify-machine',action='append',choices=['ste','megaste'])
    parser.add_argument('--unattended',action='store_true',help='verify without injecting any keys')
    args = parser.parse_args()
    out = args.out.resolve()
    build(out)
    if args.verify:
        verify(out,args.verify_machine or ['ste','megaste'],not args.unattended)
    package(out)


if __name__ == '__main__':
    main()
