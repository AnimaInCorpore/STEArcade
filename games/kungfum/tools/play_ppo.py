"""Train a coverage policy in native MAME, or record it in the existing RLE format.

    python play_ppo.py train --steps 4096
    python play_ppo.py record --model build/kungfum/ppo/policy.zip --seed 1
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import os
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'engine')]
import playbot
from ppo_env import KungFuEnv, inputs


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata():
    import platform
    exe = Path(os.environ.get('MAME') or shutil.which('mame')).resolve()
    version = subprocess.run([str(exe), '-help'], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    return dict(mame_version=version, mame_sha256=sha(exe), rom_archive_sha256=sha(ROOT/'assets/roms/kungfum.zip'),
                macos=platform.mac_ver()[0], machine=platform.machine(), python=platform.python_version(),
                versions={p: importlib.metadata.version(p) for p in ('torch', 'stable-baselines3', 'gymnasium')},
                sources={p.name: sha(p) for p in [Path(__file__), HERE/'ppo_env.py', HERE/'ppo_mame.py', HERE/'ppo_mame.lua']})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=['train', 'record'])
    ap.add_argument('--steps', type=int, default=4096, help='training decisions, each 12 arcade frames')
    ap.add_argument('--frames', type=int, default=3600)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--out', type=Path, default=ROOT/'build/kungfum/ppo')
    ap.add_argument('--model', type=Path)
    ap.add_argument('--random', action='store_true', help='record matched-action baseline without PPO')
    args = ap.parse_args()
    if args.steps < 256 or args.frames <= 900 or (args.frames-900) % 12:
        ap.error('steps >=256; frames >900 and (frames-900) divisible by 12 required')
    args.out.mkdir(parents=True, exist_ok=True)
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    torch.set_num_threads(2)
    start = time.monotonic()
    env = KungFuEnv(args.out / ('train' if args.mode == 'train' else f'record_{args.seed}'), args.frames)
    try:
        if args.mode == 'train':
            class Log(BaseCallback):
                def _on_step(self):
                    if self.num_timesteps % 256 == 0:
                        print(json.dumps(dict(step=self.num_timesteps, seconds=time.monotonic()-start,
                                              **self.locals['infos'][0])), flush=True)
                    return True
            model = PPO('MlpPolicy', env, device='cpu', seed=args.seed, n_steps=256, batch_size=64,
                        n_epochs=4, learning_rate=3e-4, ent_coef=.02, gamma=.99,
                        policy_kwargs=dict(net_arch=dict(pi=[64,64], vf=[64,64])), verbose=0)
            model.learn(total_timesteps=args.steps, callback=Log())
            model.save(args.out / 'policy')
            report = dict(mode='train', requested_steps=args.steps, actual_steps=model.num_timesteps,
                          seed=args.seed, episode_frames=args.frames, decision_frames=12,
                          parameters=sum(p.numel() for p in model.policy.parameters()),
                          seconds=time.monotonic()-start, coverage=len(env.global_seen),
                          pcs=sorted(env.global_seen), checkpoint_sha256=sha(args.out/'policy.zip'), **metadata())
            (args.out/'training.json').write_text(json.dumps(report, indent=2)+'\n')
        else:
            if not args.random and args.model is None:
                ap.error('record requires --model or --random')
            model = None if args.random else PPO.load(args.model, device='cpu')
            if model:
                model.set_random_seed(args.seed)
            rng = random.Random(args.seed)
            obs, _ = env.reset(seed=args.seed)
            frames = [(247 if 700 <= t < 704 else 254 if 760 <= t < 764 else 255, 255) for t in range(900)]
            states = [dict(env.state, ram=env.state['ram'].hex(), sprites=env.state['sprites'].hex())]
            done = False
            while not done:
                action = rng.randrange(21) if model is None else int(model.predict(obs, deterministic=False)[0])
                frames.extend(inputs(action, env.state['frame']))
                obs, _, _, done, info = env.step(action)
                states.append(dict(env.state, ram=env.state['ram'].hex(), sprites=env.state['sprites'].hex(), action=action))
            name = f'{"random" if args.random else "ppo"}_{args.seed}'
            path = args.out / f'{name}.bin'
            path.write_bytes(playbot.encode(frames))
            (args.out/f'{name}.states.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in states))
            report = dict(mode='record', seed=args.seed, frames=len(frames), **info,
                          seconds=time.monotonic()-start, replay_sha256=sha(path),
                          checkpoint_sha256=sha(args.model) if model else None,
                          states_sha256=sha(args.out/f'{name}.states.jsonl'),
                          pcs=sorted(env.seen), **metadata())
            (args.out/f'{name}.json').write_text(json.dumps(report, indent=2)+'\n')
            print(json.dumps({k:v for k,v in report.items() if k not in ('sources','pcs')}, indent=2), flush=True)
    finally:
        env.close()


if __name__ == '__main__':
    main()
