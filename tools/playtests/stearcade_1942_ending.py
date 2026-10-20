"""Retain assisted ending exploration and replay all inputs/checkpoints in Hatari."""
import argparse
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stearcade_replay_support as play
from stearcade_1942_regression import symbols


class Live(play.Live):
    def _watch(self):
        while self.proc.poll() is None:
            if self.pending is None and time.monotonic()-self.last > 120:
                (self.out/'watchdog.json').write_text(json.dumps(dict(
                    ticks=self.ticks,seconds=time.monotonic()-self.last)))
                self.proc.kill()
                break
            time.sleep(0.2)
        self.pipe.unblock()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--extend', type=int, default=20000)
    args = ap.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = out/'program'; work.mkdir()
    for f in (source/'program').glob('*.s'):
        shutil.copy2(f, work/f.name)
    with (out/'build.log').open('w') as log:
        for cmd in ([play.VASM,'-Fvobj','-quiet','-nowarn=2047','-I',str(play.STE/'build/1942'),
                     '-I',str(play.RT_INCLUDE),'-o',str(work/'game.o'),'1942.s'],
                    [play.VLINK,'-b','ataritos','-s','-o',str(work/'GAME.PRG'),
                     '-M'+str(work/'game.map'),str(work/'game.o')]):
            subprocess.run(cmd,cwd=work,stdout=log,stderr=log,check=True)
    old, sym = symbols(source/'program/game.map'), symbols(work/'game.map')
    original = json.loads((source/'manifest.json').read_text())
    for path, key in [(source/'program/GAME.PRG','program_sha256'),(play.HATARI,'hatari_sha256'),(play.TOS,'tos_sha256')]:
        assert play.sha(path) == original[key], key
    manifest = dict(program_sha256=play.sha(work/'GAME.PRG'),hatari_sha256=play.sha(play.HATARI),
                    tos_sha256=play.sha(play.TOS),source=str(source),source_program_sha256=original['program_sha256'],
                    extend=args.extend,translation_sha256=play.sha(play.STE/'build/1942/code_1942.s'))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    with gzip.open(source/'states.jsonl.gz','rt') as f:
        expected = {r['tick']:bytes.fromhex(r['ram']) for r in map(json.loads,f)}
    def relocate(c):
        m = re.fullmatch(r"w 'TEXT\+\$([0-9a-f]+)' (\$[0-9a-f]+)",c)
        assert m, c
        a = int(m[1],16)-old['g_block']
        assert 0x6000 <= a < 0x7000
        return f"w 'TEXT+${sym['g_block']+a:x}' {m[2]}"
    h = Live(out/'hatari',work,sym,'1942')
    timeline=gzip.open(out/'timeline.jsonl.gz','wt'); states=gzip.open(out/'states.jsonl.gz','wt')
    events=(out/'events.jsonl').open('w')
    report=dict(ticks=0,checked=0,failure=None,transitions=[],markers={})
    tick=0; ram=None; armed=False
    def event(kind,**kw):
        row=dict(tick=tick,kind=kind,**kw);events.write(json.dumps(row)+'\n');events.flush()
        print(json.dumps(row),flush=True)
    def step(system,player,extra):
        nonlocal tick,ram,armed
        timeline.write(json.dumps([tick,system,player,extra])+'\n');timeline.flush()
        diagnostic=[]
        if ram is not None and ram[0x103]==32 and not armed:
            for name,pc in [('ending_complete',0x70B4),('post_ending_game_over',0x6996),('stage_setup',0x14FE)]:
                path=out/(name+'.ini')
                path.write_text('\n'.join([
                    f"savebin {(out/(name+'.ram')).as_posix()} 'TEXT+${h.base:x}' $1000",
                    *play.capture_commands(out,sym,'1942',name)])+'\n')
                diagnostic.append(f"b pc = 'TEXT+${sym['Z%04X'%pc]:x}' :once :trace :quiet :file {path.as_posix()}")
            armed=True
        capture=h.step([f"w 'TEXT+${sym['dream_system']:x}' ${system:x}",
                        f"w 'TEXT+${sym['dream_player']:x}' ${player:x}",*extra,*diagnostic])
        tick+=1;report['ticks']=tick
        assert capture[1]==bytes([system,player]), f'input at {tick}'
        previous=ram;ram=capture[0]
        if tick in expected:
            assert ram==expected[tick],f'RAM checkpoint at {tick}'
            report['checked']+=1
        if tick%120==0:
            states.write(json.dumps(dict(tick=tick,ram=ram.hex()))+'\n');states.flush()
        if previous is not None and ram[0x103]!=previous[0x103]:
            report['transitions'].append([tick,previous[0x103],ram[0x103]])
            event('stage',old=previous[0x103],new=ram[0x103])
        for name in ['ending_complete','post_ending_game_over','stage_setup']:
            if name not in report['markers'] and (out/(name+'.ram')).exists():
                report['markers'][name]=tick;event(name)
        if tick%6000==0:event('progress',checked=report['checked'],stage=ram[0x103])
    try:
        h.step()
        with gzip.open(source/'timeline.jsonl.gz','rt') as f:
            for t,system,player,extra in map(json.loads,f):
                assert t==tick
                step(system,player,[relocate(c) for c in extra if not c.startswith(('screenshot ','savebin '))])
        event('retained_inputs_complete')
        start=tick
        for i in range(args.extend):
            extra=[];system=255;player=[0xEF,0xEE,0xEF,0xED][(i//120)%4]
            if ram[0x103]<32:
                extra=[f"w 'TEXT+${h.base+off:x}' ${val:x}" for off,val in [(0x101,6),(0xa5,2)]]
                if tick%1200==0:
                    extra += [f"w 'TEXT+${h.base+off:x}' ${val:x}" for off,val in [(0xbd0,7),(0x99,1),(0x102,0x43)]]
            # Allow the ending to clear lives and return through its real game-over path.
            complete=report['markers'].get('post_ending_game_over')
            if complete is not None and tick-complete>600:
                phase=(tick-complete-600)%1200
                if phase<4:system=0x7f
                if 50<=phase<56:system=0xfe
            step(system,player,extra)
        report['extended_ticks']=tick-start
    except Exception as exc:
        report['failure']=repr(exc);event('failure',error=repr(exc))
    finally:
        report['process_returncode_before_close']=h.proc.poll()
        h.close();timeline.close();states.close();events.close()
    report['crash']=(work/'CRASH.TXT').read_text() if (work/'CRASH.TXT').exists() else None
    report['passed']=report['failure'] is None and report['crash'] is None and report['checked']==len(expected)
    (out/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    return not report['passed']


if __name__=='__main__':raise SystemExit(main())
