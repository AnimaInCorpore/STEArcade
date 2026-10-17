"""Run an existing port logic test with an isolated PPO recording/build.

Only test input providers and simulator paths are redirected; comparisons, reference
CPU schedules and dead-stack exclusions remain those of the existing test. No
canonical program, map or recording is replaced. No Torch dependency is required.
"""
import argparse
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from ppo_profiles import ROOT,profile
from playbot import load
from paths import VASM,VLINK,RT_INCLUDE


def check(game,recording):
    p=profile(game);recording=Path(recording).resolve();controls=load(recording)
    tools=ROOT/'games'/game/'tools';source=ROOT/'games'/game/'src'
    sys.path[:0]=[str(tools),str(tools.parent/'ref'),str(ROOT/'engine')]
    with tempfile.TemporaryDirectory(prefix='ste-ppo-sim-') as directory:
        work=Path(directory);assets=work/'assets';assets.mkdir()
        for item in (ROOT/'build'/game).iterdir():
            if item.is_file() and item.name!='play_inputs.bin':os.symlink(item,assets/item.name)
        (assets/'play_inputs.bin').write_bytes(recording.read_bytes())
        prg,mapfile,obj=work/'PPO.PRG',work/'replay.map',work/'replay.o'
        if game!='dkong':
            defs=['-DSIM=1']+(['-DPLAYBACK=1'] if p['legacy'] else [])
            subprocess.run([VASM,'-Fvobj','-quiet','-nowarn=2047',*defs,'-I',str(assets),'-I',str(RT_INCLUDE),
                            '-o',str(obj),f'{game}.s'],cwd=source,check=True)
            subprocess.run([VLINK,'-b','ataritos','-s','-o',str(prg),'-M'+str(mapfile),str(obj)],check=True)
        testfile=tools/'logic_test.py'
        spec=importlib.util.spec_from_file_location('ppo_existing_logic_test',testfile)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        if game=='dkong':
            # DK's existing test drives the translated CPU at a fixed number of
            # idle-loop visits per NMI instead of using a SIM PRG.
            mod.BUILD=work
            original=mod.Lock.set_inputs;calls=[0]
            def native_inputs(lock,in0,in1,in2,dsw):
                i=calls[0]-1;calls[0]+=1
                s,b=controls[i] if i>=0 else (0,0)
                return original(lock,b,0,s,dsw)
            mod.Lock.set_inputs=native_inputs
        else:
            original=mod.Sim
            class Isolated(original):
                def __init__(self,*args,**kwargs):
                    kwargs['run_dir']=work
                    super().__init__(str(prg),**kwargs)
                def symbols(self,path):return super().symbols(mapfile)
            mod.Sim=Isolated
            if hasattr(mod,'BUILD'):mod.BUILD=assets
            if hasattr(mod,'build_dir'):mod.build_dir=lambda g:assets if g==game else ROOT/'build'/g
        argv=[str(testfile),str(len(controls))]
        if p['legacy']:
            if game=='ddragon':
                mod.cover.build_dir=lambda g:assets if g==game else ROOT/'build'/g
                argv+=['--seed','-1']
            elif game=='commando':argv+=['play']
            else:argv+=['--play']
        elif game=='bublbobl':mod.inputs=lambda f:(*controls[f],255)
        elif game=='1942':mod.inputs=lambda f,rnd:(*controls[f],255)
        elif game=='rtype':
            def press(machine,f,*unused):
                system,player=controls[f]
                machine.in0=0xff00|player;machine.in1=0xff00|system
            mod.cover.press=press
        sys.argv=argv
        rc=mod.main()
        if rc:raise RuntimeError(f'{game} independent replay test failed ({rc})')
    print(f'PPO independent logic replay: {game}, {len(controls)} frames passed',flush=True)
    return len(controls)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('game');ap.add_argument('recording',type=Path)
    args=ap.parse_args();check(args.game,args.recording)
