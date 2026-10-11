"""Build COMMANDO.PRG for an unexpanded 4 MB Atari STE (the main CPU ROM is embedded: build/commando/maincpu.rom)."""
from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'engine'))
from paths import ROOT,build_dir
from toolchain import assemble_link
from prepare import prepare
import gen,assets

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sim',action='store_true');ap.add_argument('--debug',action='store_true')
    ap.add_argument('--assets',action='store_true',help='regenerate and validate graphics and palette assets')
    ap.add_argument('--sound',action='store_true',help='regenerate the sound effects and the music (sfx_data.s, music_data.s, from the sound driver)')
    ap.add_argument('--frames',type=int,default=0);ap.add_argument('-D',dest='defines',action='append',default=[])
    a=ap.parse_args();prepare()
    if a.assets or not (build_dir("commando")/"spr_code.s").exists(): assets.build()
    if a.sound or not (build_dir('commando')/'sfx_data.s').exists():
        import sound_sfx;print('sfx_data.s: %d bytes'%sound_sfx.emit(build_dir('commando')/'sfx_data.s'))
    if a.sound or not (build_dir('commando')/'music_data.s').exists():
        import sound_music
        if a.sound:sound_music.all_tunes(True)
        print('music_data.s: %d bytes'%sound_music.emit(build_dir('commando')/'music_data.s'))
    text,em,code,missing=gen.generate()
    (build_dir('commando')/'code_commando.s').write_text(text)
    print(f'Translated {len(code)} instructions; {len(em.unsupported)} explicit unsupported traps')
    for u in em.unsupported:print(u)
    tag='commando_sim' if a.sim else 'commando';run=ROOT/'run'/tag;run.mkdir(parents=True,exist_ok=True)
    defs=a.defines+(['SIM=1'] if a.sim else [])+(['DEBUG=1'] if a.debug else [])
    if a.frames:defs.append(f'FRAMES={a.frames}')
    assemble_link('commando','commando.s',tag,str(run/'COMMANDO.PRG'),defs)
    print('Built',run/'COMMANDO.PRG')
if __name__=='__main__':main()
