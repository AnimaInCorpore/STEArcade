"""Synchronous, isolated MAME transport for shared PPO profiles."""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
from ppo_profiles import ROOT,rompath,coverage_candidates


def lua(value):
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,str):return json.dumps(value)
    if isinstance(value,dict):return '{'+','.join('['+json.dumps(k)+']='+lua(v) for k,v in value.items())+'}'
    return '{'+','.join(lua(v) for v in value)+'}'


class Mame:
    def __init__(self,p,log=None,timeout=120):
        self.p=p;self.temp=tempfile.TemporaryDirectory(prefix='ste-ppo-')
        self.dir=Path(self.temp.name);self.timeout=timeout
        path=rompath(p,self.dir)
        cfg=dict(p,candidates=coverage_candidates(p))
        config=self.dir/'config.lua';config.write_text('return '+lua(cfg)+'\n')
        self.log=open(log or self.dir/'mame.log','wb')
        exe=os.environ.get('MAME') or shutil.which('mame')
        if not exe:raise RuntimeError('MAME not found; set MAME')
        self.process=subprocess.Popen([exe,p['set'],'-rompath',path,'-video','none','-sound','none',
          '-nothrottle','-skip_gameinfo','-debug','-debugger','none','-autoboot_delay','0',
          '-autoboot_script',str(ROOT/'engine/ppo_mame.lua'),'-seconds_to_run','0'],
          cwd=self.dir,env=dict(os.environ,PPO_CONFIG=str(config)),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log)
        self.buffer=b''

    def step(self,inputs):
        if not 1<=len(inputs)<=1000:raise ValueError('step must contain 1..1000 frames')
        encoded=bytes(v for pair in inputs for v in pair).hex()
        self.process.stdin.write(f'step {len(inputs)} {encoded}\n'.encode());self.process.stdin.flush()
        deadline=time.monotonic()+self.timeout
        while True:
            if b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                if line.startswith(b'PPO1 '):
                    _,frame,ram,pcs=line.decode().split(' ',3)
                    return dict(frame=int(frame),ram=bytes.fromhex(ram),pcs=[int(a,16) for a in pcs.split(',') if a])
                self.log.write(line+b'\n');self.log.flush()
                continue
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([self.process.stdout],[],[],remaining)[0]:
                raise TimeoutError('MAME PPO bridge timeout; see its log')
            data=os.read(self.process.stdout.fileno(),65536)
            if not data:raise RuntimeError('MAME exited; see its log (ROM/configuration error)')
            self.buffer+=data

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b'quit\n');self.process.stdin.flush();self.process.wait(timeout=5)
            except (BrokenPipeError,subprocess.TimeoutExpired):self.process.kill();self.process.wait()
        self.process.stdin.close();self.process.stdout.close();self.log.close();self.temp.cleanup()
