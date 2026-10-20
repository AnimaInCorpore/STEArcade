"""Retain assisted DK board completions and difficulty progression in Hatari."""
import argparse
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stearcade_replay_support as play
from stearcade_1942_ending import Live
from stearcade_1942_regression import symbols


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--extend',type=int,default=16000)
    args=ap.parse_args();source=args.source.resolve();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False);work=out/'program';work.mkdir()
    for f in (source/'program').glob('*.s'):shutil.copy2(f,work/f.name)
    with (out/'build.log').open('w') as log:
        for cmd in ([play.VASM,'-Fvobj','-quiet','-nowarn=2047','-I',str(play.STE/'build/dkong'),
                     '-I',str(play.RT_INCLUDE),'-o',str(work/'game.o'),'dkong.s'],
                    [play.VLINK,'-b','ataritos','-s','-o',str(work/'GAME.PRG'),
                     '-M'+str(work/'game.map'),str(work/'game.o')]):
            subprocess.run(cmd,cwd=work,stdout=log,stderr=log,check=True)
    old=symbols(source/'program/game.map');sym=symbols(work/'game.map')
    original=json.loads((source/'manifest.json').read_text())
    for path,key in [(source/'program/GAME.PRG','program_sha256'),(play.HATARI,'hatari_sha256'),(play.TOS,'tos_sha256')]:
        assert play.sha(path)==original[key],key
    manifest=dict(program_sha256=play.sha(work/'GAME.PRG'),hatari_sha256=play.sha(play.HATARI),
                  tos_sha256=play.sha(play.TOS),source=str(source),source_program_sha256=original['program_sha256'],
                  extend=args.extend,capture_start=original.get('capture_start',22200),
                  translation_sha256=play.sha(play.STE/'build/dkong/dk_code.s'))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    with gzip.open(source/'states.jsonl.gz','rt') as f:
        expected={r['tick']:bytes.fromhex(r['ram']) for r in map(json.loads,f)}
    def relocate(c):
        m=re.fullmatch(r"w 'TEXT\+\$([0-9a-f]+)' (\$[0-9a-f]+)",c);assert m,c
        a=int(m[1],16)-old['z80_block'];assert 0x6000<=a<0x6c00
        return f"w 'TEXT+${sym['z80_block']+a:x}' {m[2]}"
    h=Live(out/'hatari',work,sym,'dkong')
    timeline=gzip.open(out/'timeline.jsonl.gz','wt');states=gzip.open(out/'states.jsonl.gz','wt')
    events=(out/'events.jsonl').open('w')
    report=dict(ticks=0,checked=0,failure=None,transitions=[],assisted_completions=[],active_boards=[])
    tick=0;ram=None;active_ticks=0;seen=set();phase_key=None;captured=set();start=10**12
    def event(kind,**kw):
        row=dict(tick=tick,kind=kind,**kw);events.write(json.dumps(row)+'\n');events.flush();print(json.dumps(row),flush=True)
    def values(r):return [r[o] for o in (0x227,0x229,0x22a,0x22b)]
    def step(system,player,extra):
        nonlocal tick,ram
        timeline.write(json.dumps([tick,system,player,extra])+'\n');timeline.flush()
        diagnostic=[]
        if ram is not None and tick>=manifest['capture_start'] and ram[0xa]==12:
            key=tuple(values(ram))
            if key not in captured:
                captured.add(key)
                diagnostic=play.capture_commands(out,sym,'dkong','board-'+'-'.join(map(str,key)))
        capture=h.step([f"w 'TEXT+${sym['dream_system']:x}' ${system:x}",
                        f"w 'TEXT+${sym['dream_player']:x}' ${player:x}",*extra,*diagnostic])
        tick+=1;report['ticks']=tick;assert capture[1]==bytes([system,player]),f'input at {tick}'
        previous=ram;ram=capture[0]
        if tick in expected:
            assert ram==expected[tick],f'RAM mismatch at {tick}'
            report['checked']+=1
        if tick%120==0:
            states.write(json.dumps(dict(tick=tick,ram=ram.hex()))+'\n');states.flush()
        if previous is not None and values(ram)!=values(previous):
            row=dict(tick=tick,old=values(previous),new=values(ram));report['transitions'].append(row);event('board_or_level',**{k:v for k,v in row.items() if k!='tick'})
        if tick%4000==0:event('progress',checked=report['checked'],board=values(ram),state=ram[0xa])
    try:
        h.step()
        with gzip.open(source/'timeline.jsonl.gz','rt') as f:
            for t,system,player,extra in map(json.loads,f):
                assert t==tick
                step(system,player,[relocate(c) for c in extra if not c.startswith(('screenshot ','savebin '))])
        start=tick;event('retained_inputs_complete',board=values(ram),state=ram[0xa])
        for i in range(args.extend):
            extra=[f"w 'TEXT+${h.base+0x228:x}' $6"]
            key=tuple(values(ram));active=ram[0xa]==12 and ram[0x200]==1
            if active:
                if key!=phase_key:
                    phase_key=key;active_ticks=0;seen.add(ram[0x227])
                    report['active_boards'].append(dict(tick=tick,board=list(key)));event('active_board',board=list(key))
                active_ticks+=1
                if active_ticks%120==0:
                    board=ram[0x227]
                    writes=[(0x290,0)]+[(o,0) for o in range(0x292,0x29a)] if board==4 else [(0x203,0x80),(0x205,0x20)]
                    extra += [f"w 'TEXT+${h.base+o:x}' ${v:x}" for o,v in writes]
                    report['assisted_completions'].append(dict(tick=tick,board=list(key),writes=writes));event('finish_assist',board=list(key))
            else:active_ticks=0
            step(0,0,extra)
        report['extended_ticks']=tick-start;report['seen_stage_types']=sorted(seen)
    except Exception as exc:
        report['failure']=repr(exc);event('failure',error=repr(exc))
    finally:
        h.close();timeline.close();states.close();events.close()
    report['crash']=(work/'CRASH.TXT').read_text() if (work/'CRASH.TXT').exists() else None
    report['loop_goal_reached']=any(
        r['old']==[4,5,120,58] and r['new']==[1,6,115,58]
        for r in report['transitions'])
    report['passed']=report['failure'] is None and report['crash'] is None and report['checked']==len(expected)
    (out/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    return not report['passed']


if __name__=='__main__':raise SystemExit(main())
