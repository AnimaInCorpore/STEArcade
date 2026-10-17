"""Explicit native-input and RAM contracts for the registered ports.

Galaga is deliberately deferred: real 51xx/54xx MCU ROMs are required for gameplay.
PPO is supplemental exploration; the curated translator coverage is never replaced.
"""
from pathlib import Path
import importlib.util
import random
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def profile(game):
    # RAM: native CPU address, byte length, corresponding STE symbol expression.
    common = dict(game=game, set=game, boot=1000, offset=0, coin=900, start=940,
                  system_idle=255, p1_idle=255, coin_mask=64, start_mask=1, start_source='system',
                  high_system=False, high_p1=False, buttons=[16,32], directions=[1,2,4,8],
                  legacy=True, cheats=[], ram=[(0xe000,0x1000,'g_block+$6000')], rom=[(0,0xbfff)])
    changes = {
        'dkong': dict(boot=600,coin=400,start=450,system_idle=0,p1_idle=0,high_system=True,high_p1=True,
                      coin_mask=128,start_mask=4,buttons=[16],directions=[1,2,8,4],legacy=False,
                      ram=[(0x6000,0xc00,'z80_block+$6000')],rom=[(0,0x5fff)]),
        'galaga': dict(deferred='Missing real 51xx.bin / 54xx.bin MCU ROMs; deferred by user.'),
        'bublbobl': dict(boot=600,coin=400,start=460,system_idle=3,high_system=True,coin_mask=4,
                         start_source='p1',start_mask=64,buttons=[32,16],directions=[2,1,0,0],legacy=False,
                         ram=[(0xe000,0x1800,'g_block+$e000')]),
        '1942': dict(coin_mask=128,legacy=False),
        '1943': dict(cheats=[(0xf206,64),(0xf214,2)]),
        'blktiger': dict(cheats=[(0xf3a0,3)]),
        'commando': dict(boot=780,coin=700,start=740,coin_mask=128,cheats=[(0xeda0,3)],
                         rom=[(0,0xbfff)]),
        'gunsmoke': dict(boot=800,coin=700,start=740,buttons=[16,32,64],cheats=[(0xe040,3)]),
        'rtype': dict(boot=120,offset=400,coin=0,start=60,coin_mask=4,buttons=[128,64],legacy=False,
                      ram=[(0x40000,0x4000,'v30_image+$40000')],rom=[],source='rtype.s'),
        'kungfum': dict(boot=900,coin=700,start=760,coin_mask=8,buttons=[128,32],cheats=[(0xe084,6)],
                        ram=[(0xe000,0x900,'g_block+$6000')],rom=[(0,0x7fff)]),
        'trojan': dict(set='trojanr',cheats=[(0xcda0,3)],ram=[(0xc000,0x1e00,'g_block+$4000')]),
        'ddragon': dict(set='ddragonj',coin=700,start=800,start_source='p1',start_mask=64,
                         directions=[1,2,8,4],buttons=[16,32,64],ram=[(0,0x1000,'g_mem')],
                         rom=[(0x4000,0xffff)]),
    }
    if game not in changes: raise ValueError(f'No PPO contract for {game}')
    common.update(changes[game])
    return common


def boot_inputs(p,t):
    s,b=p['system_idle'],p['p1_idle']
    def press(value,mask,high): return value|mask if high else value&~mask
    if p['coin']<=t<p['coin']+4: s=press(s,p['coin_mask'],p['high_system'])
    if p['start']<=t<p['start']+6:
        if p['start_source']=='system':s=press(s,p['start_mask'],p['high_system'])
        else:b=press(b,p['start_mask'],p['high_p1'])
    return s,b


def actions(p):
    # Fixed per-profile action vocabulary; native bytes retain existing replay contracts.
    right,left,down,up=p['directions']
    dirs=list(dict.fromkeys([0,right,left,down,up,right|up,left|up,right|down,left|down]))
    buttons=[0]+p['buttons']
    out=[]
    for d in dirs:
        for b in buttons:
            out.append([((d|(b if t%4<2 else 0)) if p['high_p1'] else 255&~(d|(b if t%4<2 else 0))) for t in range(12)])
    return out


def coverage_candidates(p):
    if p['game']=='rtype':
        # V30 physical ROM space is large: use the union of statically translated
        # instruction starts, not every byte. This is explicitly a bounded metric.
        text=(ROOT/'build/rtype/code_main.s').read_text()
        return sorted({int(x,16) for x in re.findall(r'^R([0-9A-Fa-f]+):',text,re.M)})
    return [a for lo,hi in p['rom'] for a in range(lo,hi+1)]


def rompath(p,temporary):
    game=p['game']
    if game in ('rtype','trojan'):
        path=ROOT/'build'/game/'mame_roms'
        if not path.exists(): raise RuntimeError(f'Run port.py prepare {game} first')
        return str(path)
    if game=='1943':
        # Use the existing checksum/name resolver, including the supplied bm.7k.
        sys.path.insert(0,str(ROOT/'games/1943/tools'))
        spec=importlib.util.spec_from_file_location('ppo_prepare1943',ROOT/'games/1943/tools/prepare.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        entries,files,_,missing=mod.verify()
        if missing:raise RuntimeError('1943 missing verified ROMs')
        p['set']='1943u' if entries[0]['name'].startswith('bmu') else '1943'
        directory=Path(temporary)/p['set'];directory.mkdir()
        for name,data in files.items():(directory/name).write_bytes(data)
        return str(temporary)
    if game=='ddragon':
        # The supplied archive is the Japanese set under its historical filename.
        directory=Path(temporary)/'ddragonj';directory.mkdir()
        import zipfile
        with zipfile.ZipFile(ROOT/'assets/roms/ddragon.zip') as archive:
            for item in archive.infolist():
                if not item.is_dir():(directory/Path(item.filename).name).write_bytes(archive.read(item))
        return str(temporary)
    return str(ROOT/'assets/roms')
