"""Kung-Fu Master RAM environment. All training transitions execute in MAME."""
from pathlib import Path
import gymnasium as gym
import numpy as np
from ppo_mame import Mame

SEG = 12
# Same 21 unique controls as the search/Kev recorder; attacks pulse 2 on / 2 off.
ACTIONS = [(d, b) for d in (2, 1, 6, 5, 0, 8, 4) for b in (0, 128, 32)]
FEATURES = 0x900 + 256 + 2


def inputs(action, start, count=SEG):
    d, b = ACTIONS[int(action)]
    return [(255, 255 & ~(d | (b if t % 4 < 2 else 0))) for t in range(start, start + count)]


def features(state):
    # No PC coverage/reward in the observation. Object/work RAM plus sprite
    # geometry; leave input latches and the stack out. Two observations expose motion.
    values = state['ram'][0x1000:0x1900] + state['sprites'] + state['scroll'].to_bytes(2, 'little')
    return np.frombuffer(values, dtype=np.uint8).astype(np.float32) / 255


class KungFuEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, out, frames=3600):
        super().__init__()
        if frames <= 900 or (frames - 900) % SEG:
            raise ValueError('episode frames must be >900 and a multiple of 12 after boot')
        self.out, self.frames = Path(out), frames
        self.action_space = gym.spaces.Discrete(len(ACTIONS))
        self.observation_space = gym.spaces.Box(0, 1, (2 * FEATURES,), np.float32)
        self.machine = None
        self.global_seen = set()
        self.episode = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        self.machine = Mame(self.out / f'episode_{self.episode:04d}')
        self.episode += 1
        self.state = self.machine.step(900)
        self.previous = features(self.state)
        self.seen, self.floors = set(), set()
        self.progress = self.deaths = 0
        return np.concatenate((self.previous, self.previous)), {}

    def step(self, action):
        before = self.state
        byte = inputs(action, before['frame'])[0][1]
        self.state = self.machine.step(SEG, p1=byte)
        now = self.state
        pcs = set(now['pcs'])
        fresh = pcs - self.global_seen
        self.global_seen.update(pcs)
        self.seen.update(pcs)
        floor = now['ram'][0x1080] & 7
        state = now['ram'][0x1000]
        moved = 0
        if state == 4 and before['ram'][0x1000] == 4 and floor == (before['ram'][0x1080] & 7):
            a, b = before['scroll'] & 0x3fff, now['scroll'] & 0x3fff
            delta = (a - b if floor % 2 == 0 else b - a) % 0x4000
            moved = delta if 0 < delta < 64 else 0
        died = now['deaths'] - before['deaths']
        self.deaths += died
        self.progress += moved
        new_floor = state == 4 and floor not in self.floors
        if state == 4:
            self.floors.add(floor)
        # Global novelty is primary; episodic coverage remains useful once the
        # global map saturates. Progress/floor bonuses help leave common loops.
        reward = .1 * len(fresh) + .002 * len(pcs) + .02 * moved + 2 * new_floor - .25 * died - .01
        current = features(now)
        obs = np.concatenate((self.previous, current))
        self.previous = current
        truncated = now['frame'] >= self.frames
        info = dict(frame=now['frame'], coverage=len(self.seen), global_coverage=len(self.global_seen),
                    new_global_pcs=len(fresh), progress_pixels=self.progress, deaths=self.deaths,
                    floors=sorted(f + 1 for f in self.floors))
        return obs, float(reward), False, truncated, info

    def close(self):
        if self.machine is not None:
            self.machine.close()
            self.machine = None
