"""Standard supplemental exploration: train/record/verify/test, per registered port.
Run through port.py ppo GAME MODE. Canonical builds and coverage are never replaced.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
from ppo_profiles import ROOT,profile,actions
from playbot import encode,load


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def contract(p):return hashlib.sha256(json.dumps(dict(profile=p,actions=actions(p)),sort_keys=True).encode()).hexdigest()
def dump(path,data):Path(path).write_text(json.dumps(data,indent=2)+'\n')


def train(args,out):
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from ppo_env import Environment
    env=Environment(args.game,out,args.frames)
    (out/'validation.json').unlink(missing_ok=True)
    start=time.monotonic()
    class Progress(BaseCallback):
        def _on_step(self):
            if self.num_timesteps%256==0:
                print(json.dumps(dict(steps=self.num_timesteps,seconds=round(time.monotonic()-start,1),**self.locals['infos'][0])),flush=True)
            return True
    try:
        torch.set_num_threads(2)
        model=PPO('MlpPolicy',env,device='cpu',seed=args.seed,n_steps=256,batch_size=64,n_epochs=4,
                  ent_coef=.02,policy_kwargs=dict(net_arch=dict(pi=[64,64],vf=[64,64])),verbose=0)
        model.learn(total_timesteps=args.steps,callback=Progress())
        model.save(out/'policy')
        metadata=dict(game=args.game,contract=contract(env.p),steps=model.num_timesteps,seed=args.seed,
                      seconds=time.monotonic()-start,coverage=len(env.global_seen),parameters=sum(p.numel() for p in model.policy.parameters()),
                      policy_sha256=sha(out/'policy.zip'),profile=env.p,
                      metric='Main CPU logical instruction-start addresses; banks and other CPUs are not separate coverage identities.',
                      candidate_scope='Static translated V30 instruction starts' if args.game=='rtype' else 'Every byte in the profile ROM ranges',
                      sources={p.name:sha(p) for p in [Path(__file__),ROOT/'engine/ppo_env.py',ROOT/'engine/ppo_profiles.py',ROOT/'engine/ppo_mame.lua',ROOT/'engine/ppo_mame.py']})
        dump(out/'training.json',metadata)
    finally:env.close()


def record(args,out):
    import torch
    from stable_baselines3 import PPO
    from ppo_env import Environment
    torch.set_num_threads(2)
    (out/'validation.json').unlink(missing_ok=True)
    meta=json.loads((out/'training.json').read_text())
    p=profile(args.game)
    if meta['contract']!=contract(p) or meta['policy_sha256']!=sha(out/'policy.zip'):raise ValueError('policy/profile mismatch; retrain this profile')
    model=PPO.load(out/'policy.zip',device='cpu');model.set_random_seed(args.seed)
    env=Environment(args.game,out,args.frames);start=time.monotonic()
    try:
        obs,_=env.reset(seed=args.seed)
        path=out/f'ppo_{args.seed}.bin';states=path.with_suffix('.states.jsonl.gz')
        with gzip.open(states,'wt') as trace:
            def snap():trace.write(json.dumps(dict(frame=env.state['frame'],ram=env.state['ram'].hex(),pcs=env.state['pcs']))+'\n')
            snap();done=False
            while not done:
                action=int(model.predict(obs,deterministic=False)[0]);obs,_,_,done,info=env.step(action);snap()
        path.write_bytes(encode(env.recording))
        dump(path.with_suffix('.json'),dict(game=args.game,contract=contract(p),frames=len(env.recording),seed=args.seed,
          coverage=len(env.seen),pcs=sorted(env.seen),seconds=time.monotonic()-start,
          replay_sha256=sha(path),states_sha256=sha(states),policy_sha256=meta['policy_sha256']))
        print(f'{args.game}: recorded {len(env.recording)} frames, {len(env.seen)} logical PCs',flush=True)
        return path
    finally:env.close()


def verify_mame(game,path,out):
    from ppo_mame import Mame
    p=profile(game);meta=json.loads(path.with_suffix('.json').read_text())
    trace=path.with_suffix('.states.jsonl.gz')
    if sha(path)!=meta['replay_sha256'] or sha(trace)!=meta['states_sha256'] or contract(p)!=meta['contract']:
        raise ValueError('recording/checkpoint/profile hash mismatch')
    controls=load(path);m=Mame(p,out/'verify-mame.log');last=0;checked=0
    try:
        if p['offset']:m.step([(p['system_idle'],p['p1_idle'])]*p['offset'])
        with gzip.open(trace,'rt') as rows:
            for line in rows:
                want=json.loads(line);end=want['frame']
                got=None
                while last<end:
                    n=min(1000,end-last);got=m.step(controls[last:last+n]);last+=n
                if got['ram'].hex()!=want['ram'] or got['pcs']!=want['pcs']:
                    raise RuntimeError(f'Native MAME replay diverges at checkpoint {end}')
                checked+=1
    finally:m.close()
    return checked


def verify(args,out,path):
    from ppo_hatari import replay
    metadata=json.loads(path.with_suffix('.json').read_text())
    if metadata['policy_sha256']!=sha(out/'policy.zip'):raise ValueError('recording was generated by a different policy; record again')
    (out/'validation.json').unlink(missing_ok=True)
    native=verify_mame(args.game,path,out)
    hatari=replay(args.game,path,out,keep=args.keep_captures)
    result=dict(game=args.game,native_mame_repeatability_checkpoints=native,hatari=hatari,
                status='transport-tested',replay_sha256=sha(path),policy_sha256=sha(out/'policy.zip'))
    dump(out/'validation.json',result)
    print(f'{args.game}: MAME repeatability {native}; Hatari inputs/checkpoints {hatari["checkpoints"]} passed',flush=True)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('game');ap.add_argument('mode',choices=['train','record','verify','test'])
    ap.add_argument('--steps',type=int,default=4096)
    ap.add_argument('--frames',type=int)
    ap.add_argument('--seed',type=int,default=1)
    ap.add_argument('--out',type=Path)
    ap.add_argument('--keep-captures',action='store_true')
    args=ap.parse_args()
    p=profile(args.game)
    if p.get('deferred'):ap.error(p['deferred'])
    if args.steps<256:ap.error('--steps must be >=256')
    if args.frames is not None and not p['boot']<args.frames<=60000:ap.error('frames must extend past boot and be <=60000')
    out=(args.out or ROOT/'build'/args.game/'ppo-standard').resolve();out.mkdir(parents=True,exist_ok=True)
    if args.mode in ('train','test'):train(args,out)
    path=out/f'ppo_{args.seed}.bin'
    if args.mode in ('record','test'):path=record(args,out)
    if args.mode in ('verify','test'):verify(args,out,path)


if __name__=='__main__':main()
