"""Shared RAM-only, coverage-directed PPO environment, without search rewinds."""
from pathlib import Path
import gymnasium as gym
import numpy as np
from ppo_profiles import profile,actions,boot_inputs
from ppo_mame import Mame

MAX_RAM=1024


class Environment(gym.Env):
    def __init__(self,game,out,frames=None):
        self.p=profile(game)
        if self.p.get('deferred'):raise RuntimeError(self.p['deferred'])
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
        self.frames=frames or self.p['boot']+2700
        if self.frames<=self.p['boot']:raise ValueError('frames must extend past boot')
        self.macros=actions(self.p);self.machine=None;self.episode=0;self.global_seen=set()
        self.action_space=gym.spaces.Discrete(len(self.macros))
        self.observation_space=gym.spaces.Box(0,1,(MAX_RAM*2,),np.float32)

    def feature(self,state):
        ram=np.frombuffer(state['ram'],np.uint8)
        # Fixed stratified addresses bound memory/model size. No coverage in observations.
        if len(ram)>MAX_RAM:ram=ram[np.linspace(0,len(ram)-1,MAX_RAM,dtype=int)]
        return np.pad(ram.astype(np.float32)/255,(0,MAX_RAM-len(ram)))

    def reset(self,*,seed=None,options=None):
        super().reset(seed=seed);self.close()
        self.machine=Mame(self.p,self.out/'mame.log');self.episode+=1
        self.recording=[]
        remaining=self.p['offset']
        while remaining:
            n=min(remaining,1000);self.machine.step([(self.p['system_idle'],self.p['p1_idle'])]*n);remaining-=n
        for start in range(0,self.p['boot'],1000):
            segment=[boot_inputs(self.p,t) for t in range(start,min(start+1000,self.p['boot']))]
            self.state=self.machine.step(segment);self.recording+=segment
        self.previous=self.feature(self.state);self.seen=set()
        return np.concatenate((self.previous,self.previous)),{}

    def step(self,action):
        controls=[(self.p['system_idle'],v) for v in self.macros[int(action)]][:self.frames-self.state['frame']]
        self.state=self.machine.step(controls);self.recording+=controls
        pcs=set(self.state['pcs']);fresh=pcs-self.global_seen
        self.global_seen|=pcs;self.seen|=pcs
        reward=.1*len(fresh)+.002*len(pcs)-.01
        current=self.feature(self.state);obs=np.concatenate((self.previous,current));self.previous=current
        return obs,reward,False,self.state['frame']>=self.frames,dict(coverage=len(self.seen),global_coverage=len(self.global_seen))

    def close(self):
        if self.machine is not None:self.machine.close();self.machine=None
