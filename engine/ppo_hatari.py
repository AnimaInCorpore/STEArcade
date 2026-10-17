"""Isolated native Hatari replay. Validates consumed-input digests and captures
RAM divergences from MAME; does not claim board/port scheduling equivalence.
"""
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
from ppo_profiles import ROOT,profile
from paths import VASM,VLINK,RT_INCLUDE
from playbot import load

# Exact insertion points before the next arcade tick; all edits are private copies.
HOOKS={
 'kungfum':('.deliver:\n','\tbsr ppo_step\n'),
 'commando':('.deliver:\n','\tbsr ppo_step\n'),
 'gunsmoke':('.deliver:\n','\tbsr ppo_step\n'),
 '1943':('.deliver:\n','    bsr ppo_step\n'),
 'blktiger':('.deliver:\n','    bsr ppo_step\n'),
 'trojan':('.deliver:\n','\tbsr ppo_step\n'),
 '1942':('.deliver:\n','\tbsr ppo_step\n'),
 'ddragon':('main_loop:\n',''),
 'dkong':('\t; Z80 NMI.\n','\tbsr ppo_step\n'),
 'bublbobl':('\tbsr\tmcu_irq\t',''),
 'rtype':('\tbsr\tport_frame\n',''),
}


def patches(game,text):
    if game=='ddragon':
        old='\taddq.w #1,cnt_ticks\n';assert old in text
        return text.replace(old,'\tbsr ppo_step\n'+old,1)
    if game=='bublbobl':
        old='\tbsr\tmcu_irq\t';assert old in text
        return text.replace(old,'\tbsr ppo_step\n'+old,1)
    if game=='rtype':
        old='\tbsr\tport_frame\n';assert old in text
        return text.replace(old,'\tbsr ppo_step\n'+old,1)
    old,insert=HOOKS[game];assert old in text,(game,old)
    return text.replace(old,old+insert,1)


def apply_source(p):
    game=p['game']
    code='ppo_apply:\n'
    if p['legacy']:
        return code+'\trts\n' # The original PLAYBACK decoder applies the same native bytes and cheats.
    if game=='dkong':
        code+='\tmove.b ppo_system,z80_block+$7f00\n\tmove.b ppo_player,z80_block+$7e00\n'
    elif game=='bublbobl':
        code+='\tmove.b ppo_system,in0_val\n\tmove.b ppo_player,in1_val\n\tmove.b #$ff,in2_val\n'
    elif game=='1942':
        code+='\tmove.b ppo_system,Z_SYSTEM\n\tmove.b ppo_player,Z_SYSTEM+1\n'
    elif game=='rtype':
        code+='\tmove.b ppo_system,in_ports+3\n\tmove.b ppo_player,in_ports+1\n'
    else:raise ValueError('missing native replay application')
    return code+'\trts\n'


def replay(game,recording,out,timeout=300,keep=False):
    p=profile(game);recording=Path(recording);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    inputs=load(recording)
    report=json.loads(recording.with_suffix('.json').read_text())
    if hashlib.sha256(recording.read_bytes()).hexdigest()!=report['replay_sha256']:raise ValueError('replay hash mismatch')
    with tempfile.TemporaryDirectory(prefix='ste-ppo-hatari-') as directory:
        work=Path(directory);src=ROOT/'games'/game/'src'
        # Local source dependencies remain available. The patched root file alone
        # is copied; no build.py, generated translation, canonical map or PRG is modified.
        for item in src.iterdir():
            if item.is_file():os.symlink(item,work/item.name)
        source=work/f'{game}.s';text=source.read_text();source.unlink()
        text=patches(game,text)
        # Recordings own the controls for the whole arcade tick, including any
        # display VBL that interrupts slow game logic or rendering.
        text=re.sub(r'^\s*jp_merge[^\n]*$', '; private PPO build: recorded controls', text, flags=re.M)
        if game=='bublbobl':text=text.replace('compose_inputs:\n','compose_inputs:\n\trts\n',1)
        if game=='rtype':text=text.replace('compose:\n','compose:\n\trts\n',1)
        if game=='bublbobl':
            text=text.replace('tcache:', '\tinclude "ppo_replay.s"\n\tsection data,data\ntcache:',1)
        else:text+='\n\tinclude "ppo_replay.s"\n'
        source.write_text(text)
        (work/'play_inputs.bin').write_bytes(recording.read_bytes())
        (work/'ppo_apply.s').write_text(apply_source(p))
        ranges='\teven\nppo_ranges:\n'+''.join(f'\tdc.l {address},{size}\n' for _,size,address in p['ram'])+'\tdc.l 0,0\n'
        # The range table is data, while ppo_apply is code.
        (work/'ppo_apply.s').write_text(apply_source(p)+'\tsection data,data\n'+ranges)
        size=sum(r[1] for r in p['ram'])
        defs=[f'-DPPO_BOOT={p["boot"]}',f'-DPPO_FRAMES={len(inputs)}',f'-DPPO_SIZE={size}']
        if p['legacy']:defs.append('-DPLAYBACK=1')
        obj,prg=work/'replay.o',work/'PPO.PRG'
        with (out/'build.log').open('w') as log:
            subprocess.run([VASM,'-Fvobj','-quiet','-nowarn=2047',*defs,'-I',str(ROOT/'build'/game),
              '-I',str(RT_INCLUDE),'-o',str(obj),source.name],cwd=work,stdout=log,stderr=log,check=True)
            subprocess.run([VLINK,'-b','ataritos','-s','-o',str(prg),str(obj)],stdout=log,stderr=log,check=True)
        hatari=os.environ.get('HATARI','/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari')
        tos=os.environ.get('TOS','/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img')
        start=time.monotonic()
        with (out/'hatari-console.log').open('w') as log:
            proc=subprocess.Popen([hatari,'--machine','ste','--memsize','4','--tos',tos,'--fast-boot','true',
              '--cpu-exact','true','--compatible','true','--sound','off','--confirm-quit','off','--statusbar','false',
              '--fast-forward','true','--log-file',str((out/'hatari.log').resolve()),str(prg)],cwd=work,stdout=log,stderr=log)
            try:
                while not (work/'PPO.OK').exists():
                    if (work/'CRASH.TXT').exists():raise RuntimeError((work/'CRASH.TXT').read_text())
                    if proc.poll() is not None or time.monotonic()-start>timeout:raise RuntimeError('Hatari replay failed/timed out; see '+str(out))
                    time.sleep(.1)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
        data=(work/'PPO.BIN').read_bytes();packet=size+6
        expected=[];digest=0
        for frame,(s,b) in enumerate(inputs):
            digest=((digest*33)^s)&65535;digest=((digest*33)^b)&65535
            n=frame+1
            if n>=p['boot'] and ((n-p['boot'])%12==0 or n==len(inputs)):expected.append((n,digest))
        if len(data)!=len(expected)*packet:raise RuntimeError('Hatari checkpoint count mismatch')
        with gzip.open(recording.with_suffix('.states.jsonl.gz'),'rt') as stream:states=[json.loads(line) for line in stream]
        if [s['frame'] for s in states]!=[f for f,_ in expected]:raise RuntimeError('MAME checkpoint frame sequence differs')
        first=None;different=0
        for i,(frame,digest) in enumerate(expected):
            row=data[i*packet:(i+1)*packet];got_frame,got_digest=struct.unpack('>IH',row[:6])
            if (frame,digest)!=(got_frame,got_digest):raise RuntimeError(f'Consumed inputs differ at frame {frame}')
            want=bytes.fromhex(states[i]['ram']);got=row[6:]
            diff=[j for j in range(size) if want[j]!=got[j]]
            if diff:
                different+=1
                if first is None:first=dict(frame=frame,bytes=len(diff),first_offsets=diff[:12])
        result=dict(game=game,frames=len(inputs),checkpoints=len(expected),input_digest='passed',
                    completed=True,native_mame_different_checkpoints=different,first_native_mame_difference=first,
                    equivalence='Native MAME and port schedules/RNG may differ; this is a transport/completion test, not port-reference equivalence.',
                    seconds=time.monotonic()-start,hatari_sha256=hashlib.sha256(Path(hatari).read_bytes()).hexdigest())
        if keep:
            with gzip.open(out/'hatari-ram.bin.gz','wb') as f:f.write(data)
        (out/'hatari.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
