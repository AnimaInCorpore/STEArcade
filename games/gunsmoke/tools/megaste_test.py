#!/usr/bin/env python3
"""Build/package Gun.Smoke's identified human-playable Mega STE test."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time, zipfile
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'engine')]
from toolchain import assemble_link
from paths import build_dir

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build(out):
    subprocess.run([sys.executable,str(Path(__file__).with_name('build.py'))],check=True)
    paths=[ROOT/'games/gunsmoke/src/gunsmoke.s',ROOT/'games/gunsmoke/src/megaste_test.s',ROOT/'engine/rt/borders.s',ROOT/'engine/rt/ikbd.s',ROOT/'engine/rt/jagpad.s']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in paths}
    defines=['DEBUG=1','MSTE_TEST=1','BD_PCLOG=1']
    identity=hashlib.sha256(json.dumps(dict(source=hashes,defines=defines),sort_keys=True).encode()).hexdigest()[:16]
    b=build_dir('gunsmoke')
    (b/'mt_build.i').write_text(f"\tdc.b 'Gun.Smoke Mega STE test 1 - {identity}',13,10,0\n")
    out.mkdir(parents=True,exist_ok=True)
    assemble_link('gunsmoke','gunsmoke.s','mste_human',str(out/'GUNSMOKE.TOS'),defines)
    shutil.copyfile(b/'mste_human.map',out/'GUNSMOKE.MAP')
    meta=dict(game='gunsmoke',test_version=1,build_id=identity,git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_sha256=hashes,executable_sha256=sha(out/'GUNSMOKE.TOS'),defines=defines,cheats=False,autoplay=False,replay=False)
    (out/'BUILD.JSN').write_text(json.dumps(meta,indent=2)+'\n')
    return meta

def packet_test(out):
    from sim import Sim
    from machine68k import Register as R
    s=Sim(out/'GUNSMOKE.TOS')
    sym={k:v+s.base for k,v in s.symbols(out/'GUNSMOKE.MAP').items()}
    for raw in range(256):
        s.mem.w32(0x8000,0x600);s.cpu.w_reg(R.A7,0x8000)
        s.cpu.w_reg(R.D0,0);s.cpu.w_reg(R.D1,raw);s.cpu.w_pc(sym['joy_bits'])
        s.cpu.execute(1000)
        expected=((raw&8)>>3)|((raw&4)>>1)|((raw&2)<<1)|((raw&1)<<3)|((raw&128)>>2)
        assert s.cpu.r_pc()==0x600 and s.cpu.r_reg(R.D0)==expected,(raw,s.cpu.r_reg(R.D0),expected)
    return dict(joystick_decoder_values=256,joystick_decoder_pass=True,scope='native conversion routine; physical joystick/IKBD transport still needs hardware exercise')

def verify(out,hatari,machine='megaste',startup60=False,stress_rounds=0):
    work=out/('VERIFY-'+machine+('-60start' if startup60 else ''));work.mkdir(exist_ok=True)
    shutil.copyfile(out/'GUNSMOKE.TOS',work/'GUNSMOKE.TOS')
    for n in ['GUNTEST.TXT','CRASH.TXT','COUNTERS.BIN','RATE.BIN','LATEPC.BIN','result.json','late-samples.json']:(work/n).unlink(missing_ok=True)
    fifo=work/'cmd.fifo';fifo.unlink(missing_ok=True)
    report=work/'GUNTEST.TXT'
    cmd=[str(hatari),'--machine',machine,'--memsize','4','--tos',os.environ.get('TOS','/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img'),'--fast-boot','true','--fast-forward','true','--cpu-exact','true','--compatible','true','--sound','off','--confirm-quit','off','--joy0','none','--joy1','none','--cmd-fifo',str(fifo),'--log-file',str(work/'hatari.log'),str(work/'GUNSMOKE.TOS')]
    sym={m[2]:int(m[1],16) for m in re.finditer(r'^\s+0x([0-9a-f]{8}) (\S+):', (out/'GUNSMOKE.MAP').read_text(),re.M)}
    if startup60:
        # Execute a real supervisor CPU write before mt_begin, using private
        # unused report-buffer RAM as a one-shot trampoline. The delivered
        # executable, its addresses and its hash are unchanged. This tests a
        # 60 Hz startup with DE TOS; it is not a US ROM/master-clock emulation.
        tmp=sym['mt_buffer']+1536
        switch=work/'switch60.ini';arm=work/'arm60.ini';entry=work/'entry60.ini'
        switch.write_text(f"w b 'TEXT+${tmp:x}' $13 $fc $00 $00 $00 $ff $82 $0a $4e $f9 $00 $00 $00 $00\nw l 'TEXT+${tmp+10:x}' 'TEXT+${sym['mt_begin']:x}'\nr pc='TEXT+${tmp:x}'\n")
        entry.write_text(f"b pc = 'TEXT+${sym['mt_begin']:x}' :once :trace :quiet :file {switch}\n")
        arm.write_text(f"b pc = TEXT && pc < $e00000 && (pc).l = $42a73f3c :once :trace :quiet :file {entry}\n")
        cmd[-1:-1]=['--parse','prg:'+str(arm)]
    def send(line):
        with fifo.open('w') as f:f.write(line+'\n')
    def until(test,seconds=30):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if (work/'CRASH.TXT').exists():raise RuntimeError((work/'CRASH.TXT').read_text())
            if test():return
            if proc.poll() is not None:raise RuntimeError('Hatari exited')
            time.sleep(.02)
        raise RuntimeError('timeout '+str(work))
    def dump(name,addr,size):
        p=work/name;p.unlink(missing_ok=True)
        send(f'hatari-debug savebin {p} 0x{addr:x} {size}')
        until(lambda:p.exists() and p.stat().st_size==size,5)
        return p.read_bytes()
    def frame():return int.from_bytes(dump('frame.bin',base+sym['frame_counter'],4),'big')
    def frames(n):
        target=frame()+n
        until(lambda:frame()>=target,30)
    samples={}
    def sample(stage):
        raw=dump('late-'+stage+'.bin',base+sym['bd_late_top'],8)
        samples[stage]=[int.from_bytes(raw[i:i+2],'big') for i in range(0,8,2)]
        (work/'late-samples.json').write_text(json.dumps(samples,indent=2)+'\n')
    def tap(code,p1mask=0):
        send(f'hatari-event keydown 0x{code:02x}')
        frames(10)
        if p1mask:
            ports=dump(f'held-{code:02x}.bin',base+sym['Z_SYSTEM'],3)
            assert ports[1]&p1mask==0,(code,ports)
        send(f'hatari-event keyup 0x{code:02x}')
        frames(6)
        sample(f'key-{code:02x}')
    env=dict(os.environ,SDL_VIDEO_DRIVER='dummy',SDL_AUDIO_DRIVER='dummy')
    with (work/'host.log').open('w') as log:
        proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=log)
        try:
            until(lambda:report.exists(),30)
            text=report.read_text();base=int(re.search(r'Text load address: ([0-9A-F]+)',text)[1],16)
            until(lambda:frame()>750,60)
            sample('ready')
            send('hatari-debug screenshot '+str(work/'attract.png'))
            tap(0x06);frames(20)
            send('hatari-debug screenshot '+str(work/'coin.png'))
            tap(0x02);frames(100)
            for code,mask in [(0x4d,1),(0x4b,2),(0x50,4),(0x48,8),(0x1d,16),(0x39,32),(0x38,64)]:tap(code,mask)
            for cycle in range(stress_rounds):
                for code,mask in [(0x4d,1),(0x4b,2),(0x50,4),(0x48,8),(0x1d,16),(0x39,32),(0x38,64)]:tap(code,mask)
            send('hatari-debug screenshot '+str(work/'play.png'))
            send('hatari-event keydown 0x01');frames(2)
            send('hatari-event keyup 0x01')
            until(lambda:'Phase (00=start,01=normal exit,02=crash): 01' in report.read_text(),30)
            text=report.read_text();assert 'Exception-vector restore mismatches (must be 0000 at exit): 0000' in text,text
            if machine=='megaste':
                assert 'Enhanced pads enabled (Mega STE must be 00): 00' in text,text
                speeds=[int(v,16)&3 for v in re.search(r'FF8E21.*: ([0-9A-F ]+)',text)[1].split()]
                assert speeds[1:3]==[3,3] and speeds[3]==speeds[0],speeds
            for label in ['Key presses','Key releases']:
                seen=set(re.search(label+r' \(hex scancodes\): ([0-9A-F ]*)',text)[1].split())
                assert {'06','02','4D','4B','50','48','1D','39','38'}<=seen,(label,seen)
            if startup60:
                assert 'Original/restored video sync (00=60Hz,02=50Hz): 00 00' in text,text
            counters=(work/'COUNTERS.BIN').read_bytes()
            late=[int.from_bytes(counters[i:i+2],'big') for i in [8,10,12,14]]
            assert late==[0]*4,late
            result=dict(machine=machine,startup60=startup60,stress_rounds=stress_rounds,fixture='real 60 Hz CPU write before startup, DE TOS, PAL master clock' if startup60 else 'normal startup',hatari_sha256=sha(hatari),program_sha256=sha(work/'GUNSMOKE.TOS'),keyboard_coin_start_and_controls=True,input_port_assertions=True,enhanced_pads_disabled=(machine=='megaste'),exception_vectors_restored=True,late=late,physical_joystick='not exercised',audio_audibility='not assessed')
            (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
        finally:
            proc.terminate();proc.wait(timeout=10)

def package(out):
    guide=(ROOT/'games/gunsmoke/docs/megaste-instructions.txt').read_text()
    (out/'README.TXT').write_bytes(guide.replace('\n','\r\n').encode('ascii'))
    message=(ROOT/'games/gunsmoke/docs/darklord-message.txt').read_text()
    (out/'DARKLORD.TXT').write_bytes(message.replace('\n','\r\n').encode('ascii'))
    with zipfile.ZipFile(out/'SOURCE.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for p in [ROOT/'games/gunsmoke/src/gunsmoke.s',ROOT/'games/gunsmoke/src/megaste_test.s',Path(__file__),Path(__file__).with_name('megaste_bench.py'),ROOT/'engine/rt/borders.s',ROOT/'engine/rt/ikbd.s',ROOT/'engine/rt/jagpad.s']:
            z.write(p,p.relative_to(ROOT))
        z.write(build_dir('gunsmoke')/'mt_build.i','build/gunsmoke/mt_build.i')
    names=['GUNSMOKE.TOS','GUNSMOKE.MAP','BUILD.JSN','README.TXT','DARKLORD.TXT','SOURCE.ZIP']
    (out/'SHA256.TXT').write_text(''.join(f'{sha(out/n)}  {n}\n' for n in names))
    with zipfile.ZipFile(out/'GUNMSTE.ZIP','w',zipfile.ZIP_DEFLATED) as z:
        for n in names+['SHA256.TXT']:z.write(out/n,n)
    print(out/'GUNMSTE.ZIP')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/gunsmoke-megaste/package')
    ap.add_argument('--verify',action='store_true')
    ap.add_argument('--hatari',type=Path,default=Path('/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari'))
    args=ap.parse_args();out=args.out.resolve();build(out)
    if args.verify:
        print(packet_test(out))
        for machine in ['megaste','ste']:verify(out,args.hatari,machine,stress_rounds=4)
        verify(out,args.hatari,'megaste',startup60=True,stress_rounds=4)
    package(out)
if __name__=='__main__':main()
