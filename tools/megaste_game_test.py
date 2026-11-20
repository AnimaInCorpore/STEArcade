"""Run one built game in cycle-exact Hatari and check its live border trace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = ROOT.parent/'F030Arcade/third_party'
SYNC = re.compile(r'sync=(0x\w+) .*?line_cyc_w=(\d+).*?video_hbl_w=(\d+)')

def verify(game, exe, out, hatari, tos, memory):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        work = Path(tmp)
        # Each process gets a private writable GEMDOS drive and command FIFO.
        program = work/exe.name
        shutil.copyfile(exe, program)
        for asset in exe.parent.glob('*.DAT'):
            shutil.copyfile(asset, work/asset.name)
        fifo, trace = work/'control', work/'trace'
        cmd = [str(hatari), '--machine','megaste','--tos',str(tos),'--memsize',str(memory),
               '--cpu-exact','true','--compatible','true','--fast-boot','true',
               '--fast-forward','true','--sound','off','--confirm-quit','off',
               '--trace','mem,video_sync,video_border_v','--trace-file',str(trace),
               '--cmd-fifo',str(fifo),str(program)]
        keys = [(760,'keydown 0x06'),(764,'keyup 0x06'),(800,'keydown 0x02'),
                (805,'keyup 0x02'),(1000,'keydown 0x48'),(1020,'keyup 0x48'),
                (1100,'keydown 0x39'),(1120,'keyup 0x39'),
                (1800,'keydown 0x01'),(1805,'keyup 0x01')]
        frames, lines, faults, clocks = 0, [], [], []
        running = restored = video_started = False
        def send(command):
            with fifo.open('w') as pipe:
                pipe.write(command+'\n')
        env = dict(os.environ, SDL_VIDEO_DRIVER='dummy', SDL_AUDIO_DRIVER='dummy')
        with (out/'host.log').open('w') as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=log, env=env)
            try:
                deadline = time.monotonic()+100
                while not trace.exists() and time.monotonic()<deadline and proc.poll() is None:
                    time.sleep(.02)
                with trace.open() as stream:
                    while time.monotonic()<deadline and proc.poll() is None and not restored:
                        offset=stream.tell()
                        line=stream.readline()
                        if not line.endswith('\n'):
                            stream.seek(offset)
                            time.sleep(.01)
                            continue
                        if 'cpu : megaste set to' in line:
                            freq=int(line.split('set to ')[1].split()[0])
                            clocks.append(freq)
                            if freq==16:
                                running=True
                            elif running:
                                restored=True
                        if not running:
                            continue
                        match=SYNC.match(line)
                        if match:
                            val,cycle,row=match.groups()
                            lines.append((int(row),int(cycle),int(val,16)))
                        if 'detect vblank=off' not in line:
                            continue
                        if not video_started:
                            video_started=any(row==33 and value==0 for row,cycle,value in lines)
                            if not video_started:
                                lines=[]
                                continue
                        frames+=1
                        if 10 < frames <= 1800:
                            valid = len(lines)==4 and all(
                                row==r and lo<=cycle<hi and value==v
                                for (row,cycle,value),(r,lo,hi,v) in zip(lines,[
                                    (33,376,500,0),(34,0,36,2),
                                    (262,376,500,0),(263,0,36,2)]))
                            if not valid:
                                faults.append((frames,lines))
                        lines=[]
                        if keys and frames==keys[0][0]:
                            send('hatari-event '+keys.pop(0)[1])
                        if frames==1550:
                            send('hatari-debug screenshot '+str(out/'screen.png'))
                            send(f'hatari-debug savebin {work}/cpu.bin $ff8e21 1')
                        if frames>2100:
                            break
            finally:
                proc.terminate()
                proc.wait(timeout=10)
        cpu=work/'cpu.bin'
        cached=cpu.is_file() and cpu.read_bytes()[0]&3==3
        crash=work/'CRASH.TXT'
        if crash.exists():
            shutil.copy(crash,out/'CRASH.TXT')
        result=dict(game=game,program_sha256=hashlib.sha256(program.read_bytes()).hexdigest(),
                    ram_mb=memory,cached=cached,frames=frames,clock_mhz=clocks,restored=restored,
                    bad_frames=len(faults),examples=faults[:8],crash=crash.exists())
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(game, frames, clocks, len(faults), faults[:1],flush=True)
        return frames>=1800 and restored and cached and not faults and not crash.exists()

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('game')
    ap.add_argument('exe',type=Path)
    ap.add_argument('--ram',type=int,default=4)
    ap.add_argument('--hatari',type=Path,default=THIRD_PARTY/'hatari/build/src/hatari')
    ap.add_argument('--tos',type=Path,default=THIRD_PARTY/'tos/tos206de.img')
    ap.add_argument('--out',type=Path,default=ROOT/'build/megaste-rollout')
    args=ap.parse_args()
    raise SystemExit(0 if verify(args.game,args.exe.resolve(),args.out.resolve()/args.game,
                                 args.hatari,args.tos,args.ram) else 1)
