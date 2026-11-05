"""Offline Alien/Zombies quantizer comparison. Never rebuilds production assets.

The JavaScript colour/palette/dither code is retained in the shared engine worker
from the Alien/Zombies demos; their source checkout is optional for verification.
Scene histograms, weighting and reserved-colour count are adapted to R-Type.
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
import pickle
import re
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(HERE),str(ROOT/"engine")]
import stage_assets as SA
from palette_quantize import oklab, balanced_weights, WORKER
from stage_test import Expected
from m72board import load_regions

MODES=('flat','checker','hybrid','balanced')
SPECS=[("title","Title","1",200,0,399,20),
       ("stage1","Stage 1 — middle section","8",4200,3500,5500,80),
       ("warship","Stage 3 — warship","3",2200,1200,2999,60),
       ("stage7","Stage 7","s7",1600,0,2999,80)]


def rgb12(c):
    c=np.asarray(c,dtype=np.int32)
    return np.stack([(c>>8)&15,(c>>4)&15,c&15],-1).astype(np.uint8)*17


def ste_palette(data):
    words=np.frombuffer(data,">u2").astype(np.int32)
    nib=np.stack([(words>>8)&15,(words>>4)&15,words&15],-1)
    return (((nib&7)<<1)|(nib>>3)).astype(np.uint8)*17


def extract(source):
    text=source.read_text()
    a=text[text.index("function srgbToLinear"):text.index("// Sprite frames.")]
    b=text[text.index("const colors = [ ...colorWeights.entries() ]"):text.index("function mirror(frame)")]
    normalized=re.sub(r"\s+","",re.sub(r"//[^\n]*","",a+b))
    return a+b,hashlib.sha256(normalized.encode()).hexdigest()


def prepare(spec,out,rom):
    slug,title,name,focus,start,end,stride=spec
    records=pickle.load(open(ROOT/("build/rtype/stage_states_"+name+".pkl"),"rb"))
    expected=Expected();captured={}
    original=expected.model.picture
    def picture(*args,**kwargs):
        captured["pens"]=original(*args,**kwargs)
        return captured["pens"]
    expected.model.picture=picture
    samples=[];chosen=None
    for i,(_,packed) in enumerate(records[:end+1]):
        st=pickle.loads(zlib.decompress(packed))
        want=expected(st)
        if i!=focus and not(start<=i<=end and (i-start)%stride==0):continue
        scene=expected.cur
        ref,pal,hpal,spm,tpm,hpm,flags,ded,frz=expected.scenes[scene]
        targets=np.frombuffer(st["recs"],np.uint8).copy()
        for row in range(16):
            if frz>>row&1:targets[16+row]=ref[row]
        source=[]
        for row,target in enumerate(targets):
            addr=0x3b000+int(target)*48+(0x2400 if row>=16 else 0)
            values=np.frombuffer(rom[addr:addr+48],np.uint8).astype(np.int32).reshape(16,3)&31
            source.extend(((values<<3)|(values>>2)).tolist())
        colors=np.array(source+[[0,0,0]],np.uint8)
        pens=captured["pens"].copy()
        arcade=colors[pens]
        native=ste_palette(pal);hud=ste_palette(hpal)
        dedicated={256+(row-16)*16+pen:idx for row,pen,idx in ded}
        frozen=dict(st);frozen["recs"]=bytes(targets)
        c12=SA.pen_colours(frozen)
        for pen,index in dedicated.items():native[index]=rgb12(c12[pen])
        current=native[want]
        if any(b[0]==240 for b in st["bands"]):current[240:]=hud[want[240:]]
        hist=collections.Counter()
        layer_hist=[collections.Counter(),collections.Counter()]
        for pen,count in zip(*np.unique(pens[:240],return_counts=True)):
            if pen==512 or int(pen) in dedicated:continue
            rgb=tuple(int(v) for v in rgb12(c12[pen]))
            hist[rgb]+=int(count)*(8 if pen<256 else 1)
            # Fit the corrected candidate to the original 5-bit arcade RGB;
            # only the chosen STE palette is snapped to four bits/channel.
            layer_hist[int(pen>=256)][tuple(map(int,colors[pen]))]+=int(count)
        item=dict(index=i,frame=records[i][0],scene=scene,hist=hist,layer_hist=layer_hist,
                  arcade=arcade,current=current,pens=pens,dedicated=dedicated,
                  native=native,hud=hud,colors=colors)
        samples.append(item)
        if i==focus:chosen=item
    assert chosen is not None
    training=[s for s in samples if s["scene"]==chosen["scene"] and start<=s["index"]<=end]
    hist=collections.Counter();layers=[collections.Counter(),collections.Counter()]
    for sample in training:
        hist.update(sample["hist"])
        for target,source in zip(layers,sample['layer_hist']):target.update(source)
    inputs=np.unique(np.concatenate([chosen["arcade"].reshape(-1,3),
                                    np.array(sorted(layers[0].keys() | layers[1].keys()),np.uint8)]),axis=0)
    base=dict(hist=[[','.join(map(str,key)),value] for key,value in sorted(hist.items())],
              input_colors=inputs.tolist(),color_count=16-len(chosen["dedicated"]))
    chosen.update(slug=slug,title=title,training_frames=len(training),inputs=inputs,
                  base=base,layers=layers)
    metadata={k:chosen[k] for k in ('slug','title','scene','frame','training_frames','base')}
    metadata['dedicated']=chosen['dedicated']
    metadata['layers']=[[[list(c),n] for c,n in h.items()] for h in layers]
    np.savez_compressed(out/(slug+'_samples.npz'),metadata=json.dumps(metadata),
                        **{k:chosen[k] for k in ('arcade','current','pens','native','inputs')})
    np.savez_compressed(out/(slug+'_frames.npz'),arcade=chosen['arcade'],current=chosen['current'],pens=chosen['pens'])
    print(slug,'scene',chosen['scene'],'training',len(training),'colours',len(hist),'free',base['color_count'],flush=True)
    return chosen


def load_sample(spec,out):
    data=np.load(out/(spec[0]+'_samples.npz'))
    item=json.loads(str(data['metadata']))
    item['dedicated']={int(k):v for k,v in item['dedicated'].items()}
    item['layers']=[collections.Counter({tuple(c):n for c,n in entries}) for entries in item['layers']]
    item.update({k:data[k] for k in ('arcade','current','pens','native','inputs')})
    return item


def make_jobs(item,out,modes,args):
    for mode in modes:
        base=item['base'];slug=item['slug']
        job=dict(base,mode=mode,dither_l=0 if mode=="flat" else .12)
        if mode=='hybrid':
            hist={tuple(map(int,c.split(','))):n for c,n in base['hist']}
            keys=np.array([(r//17<<8)|(g//17<<4)|(b//17) for r,g,b in sorted(hist)],np.int32)
            lab=SA.MP.lab12(keys).astype(float)
            chroma=np.hypot(lab[:,1]-128,lab[:,2]-128)/128
            weight=np.sqrt(np.array([hist[c] for c in sorted(hist)],float))*(1+40*chroma)
            job['hist']=[[','.join(map(str,color)),float(w)] for color,w in zip(sorted(hist),weight)]
        if mode=='balanced':
            job['hist']=balanced_weights(item['layers'],args.frequency_power,args.chroma_gain,args.sprite_weight)
            job['weighting']=dict(frequency_power=args.frequency_power,chroma_gain=args.chroma_gain,
                                  sprite_weight=args.sprite_weight)
        (out/(slug+'_'+mode+'.json')).write_text(json.dumps(job))


def run_job(worker,path):
    result=path.with_suffix('.result.json')
    with result.open('w') as output:
        subprocess.run(['node',str(worker)],input=path.read_bytes(),stdout=output,check=True)
    return result


def training_error(item,result):
    """Unbiased pixel error, independent of the palette-fitting weights.

    Evaluate a checker by its linear-RGB mix, as the demos do. These figures
    measure colour reproduction, not spatial checker texture or movement.
    """
    palette=np.array(result['palette'],float)/255
    linear=np.where(palette>.04045,((palette+.055)/1.055)**2.4,palette/12.92)
    choices={tuple(c):v for c,v in zip(item['inputs'].tolist(),result['choices'])}
    metrics={}
    for name,hist in zip(('sprites','tiles'),item['layers']):
        colors=np.array(sorted(hist),np.uint8)
        if not len(colors):continue
        count=np.array([hist[tuple(c)] for c in colors],float)
        pairs=[choices[tuple(c)] for c in colors]
        mixed=np.array([(linear[c['first']]+linear[c['second']])/2 for c in pairs])
        encoded=np.where(mixed>.0031308,1.055*mixed**(1/2.4)-.055,12.92*mixed)*255
        source=oklab(colors);dest=oklab(encoded)
        delta=dest-source
        masks={'all':np.ones(len(colors),bool),
               'neutral':np.linalg.norm(source[:,1:],axis=1)<.06,
               'chromatic':np.linalg.norm(source[:,1:],axis=1)>=.1}
        metrics[name]={}
        for group,mask in masks.items():
            if not mask.any():continue
            weight=count[mask]
            metrics[name][group]=dict(mean_delta_e=float(np.average(np.linalg.norm(delta[mask],axis=1),weights=weight)*100),
                                     chroma_error=float(np.average(np.linalg.norm(delta[mask,1:],axis=1),weights=weight)*100))
    return metrics


def make_panels(item,out):
    slug=item['slug'];outputs={};stats={}
    reference=item['arcade'];current=item['current']
    y,x=np.indices(reference.shape[:2]);phase=(x+y)&1
    for mode in MODES:
        result=json.loads((out/(slug+'_'+mode+'.result.json')).read_text())
        palette=np.array(result['palette'],np.uint8)
        assert len(result['choices'])==len(item['inputs']),(slug,mode,'incomplete lookup table')
        assert len(palette)==item['base']['color_count'] and np.all(palette%17==0)
        assert np.all(palette[0]==0),(slug,mode,'black must remain fixed')
        lut={tuple(c):v for c,v in zip(item['inputs'].tolist(),result['choices'])}
        mapped=np.zeros_like(reference);dithered=np.zeros(reference.shape[:2],bool)
        for color,choice in lut.items():
            mask=np.all(reference==color,axis=2)
            mapped[mask&(phase==0)]=palette[choice['first']]
            mapped[mask&(phase==1)]=palette[choice['second']]
            if choice['first']!=choice['second']:dithered|=mask
        # Keep R-Type's reserved changing pens and existing HUD in this test.
        for pen,index in item['dedicated'].items():
            mapped[item['pens']==pen]=item['native'][index]
            dithered[item['pens']==pen]=False
        mapped[item['pens']==512]=0
        dithered[item['pens']==512]=False
        mapped[240:]=current[240:]
        outputs[mode]=mapped
        unique=np.unique(mapped[:240].reshape(-1,3),axis=0)
        assert len(unique)<=16,(slug,mode,len(unique))
        assert np.all(unique%17==0)
        Image.fromarray(mapped).save(out/(slug+'_'+mode+'.png'))
        stats[mode]=dict(palette=palette.tolist(),dithered_fraction=float(dithered[:240].mean()),visible_colors=len(unique),
                        training_error=training_error(item,result))
    for mode,pixels in [('arcade',reference),('current',current)]:Image.fromarray(pixels).save(out/(slug+'_'+mode+'.png'))
    font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',22)
    labels=['Arcade target colours','Current STE','Demo method — flat','Demo method — checker','Old saturation weighting','Bounded saturation weighting']
    panel=Image.new('RGB',(len(labels)*640,562),'#161d26');draw=ImageDraw.Draw(panel)
    for k,(label,pixels) in enumerate(zip(labels,[reference,current]+[outputs[m] for m in MODES])):
        draw.text((k*640+12,12),label,font=font,fill='white')
        panel.paste(Image.fromarray(pixels).resize((640,512),Image.Resampling.NEAREST),(k*640,50))
    panel.save(out/(slug+'_comparison.png'))
    for mode in ('checker','hybrid','balanced'):
        pair=Image.new('RGB',(1280,562),'#161d26');draw=ImageDraw.Draw(pair)
        label={'checker':'Demo method — checker','hybrid':'Old saturation weighting','balanced':'Bounded saturation weighting'}[mode]
        for k,(label,pixels) in enumerate(zip(['Current STE',label],[current,outputs[mode]])):
            draw.text((k*640+12,12),label,font=font,fill='white')
            pair.paste(Image.fromarray(pixels).resize((640,512),Image.Resampling.NEAREST),(k*640,50))
        pair.save(out/(slug+'_'+mode+'_pair.png'))
    for suffix,labels,images in [('weighting_pair',['Old saturation weighting','Bounded saturation weighting'],[outputs['hybrid'],outputs['balanced']]),
                                 ('weighting_comparison',['Arcade target colours','Old saturation weighting','Bounded saturation weighting'],[reference,outputs['hybrid'],outputs['balanced']])]:
        panel=Image.new('RGB',(len(images)*640,562),'#161d26');draw=ImageDraw.Draw(panel)
        for k,(label,pixels) in enumerate(zip(labels,images)):
            draw.text((k*640+12,12),label,font=font,fill='white')
            panel.paste(Image.fromarray(pixels).resize((640,512),Image.Resampling.NEAREST),(k*640,50))
        panel.save(out/(slug+'_'+suffix+'.png'))
    return dict(scene=item['scene'],frame=item['frame'],training_frames=item['training_frames'],**stats)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--demos',type=Path,help='Optionally verify the retained algorithm against the original demos')
    ap.add_argument('--out',type=Path,default=ROOT/'build/rtype/quantization_preview')
    ap.add_argument('--reuse-samples',action='store_true',help='Reuse the previously captured frame/sample cache')
    ap.add_argument('--modes',nargs='+',choices=MODES,default=MODES,help='Recompute these variants; other results must already exist')
    ap.add_argument('--frequency-power',type=float,default=.75)
    ap.add_argument('--chroma-gain',type=float,default=1,help='Maximum extra saturation weight (default caps the total below 2x)')
    ap.add_argument('--sprite-weight',type=float,default=8,help='Sprite multiplier applied after count compression')
    args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if not 0<args.frequency_power<=1 or not 0<=args.chroma_gain<=4 or not 0<args.sprite_weight<=32:
        ap.error('Require 0 < frequency-power <= 1, 0 <= chroma-gain <= 4, 0 < sprite-weight <= 32')
    ha='e469f9d6da5398c44528b0e01f2444be08d67dfd0f33592079be71c84e02edbf'
    if args.demos:
        _,a=extract(args.demos/'demos/alien/make_alien.js')
        _,b=extract(args.demos/'demos/zombies/make_zombies.js')
        assert a==b==ha,'Demo quantizers differ; review before comparing.'
    worker=WORKER
    if args.reuse_samples:
        items=[load_sample(spec,out) for spec in SPECS]
    else:
        rom=load_regions('rtype')['main']
        items=[prepare(spec,out,rom) for spec in SPECS]
    for item in items:make_jobs(item,out,args.modes,args)
    jobs=[out/(item['slug']+'_'+mode+'.json') for item in items for mode in args.modes]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for path in pool.map(lambda path:run_job(worker,path),jobs):print('quantized',path.name,flush=True)
    results={item['slug']:make_panels(item,out) for item in items}
    policies=[json.loads((out/(item['slug']+'_balanced.json')).read_text())['weighting'] for item in items]
    assert all(p==policies[0] for p in policies),'Recompute balanced variants with one consistent policy'
    policy=policies[0];power=policy['frequency_power'];gain=policy['chroma_gain'];sprite_weight=policy['sprite_weight']
    policy.update(formula=f'({sprite_weight:g} * sprite_pixels^{power:g} + tile_pixels^{power:g}) * (1 + {gain:g} * C^2 / (C^2 + 0.1^2))',
                  fit_source='Original 5-bit arcade RGB; palette snapped to STE RGB')
    (out/'results.json').write_text(json.dumps(dict(demo_algorithm_sha256=ha,balanced_weighting=policy,scenes=results),indent=2)+'\n')
    cards=[]
    for item in items:
        slug=item['slug']
        cards.append('<h2>'+item['title']+'</h2><img src="'+slug+'_weighting_comparison.png" alt="Arcade, old weighting, corrected weighting"><p>Left: arcade target colours in the same composition. Middle: previous saturation weighting. Right: bounded saturation weighting.</p><details><summary>All six variants</summary><img src="'+slug+'_comparison.png" alt="Six colour treatments"><p>Arcade target; installed STE palette; demo flat; demo checker; old saturation weighting; bounded saturation weighting.</p></details>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>R-Type quantization comparison</title><style>body{background:#111820;color:#edf3fa;font:16px system-ui;margin:24px}img{max-width:100%;image-rendering:pixelated}p{max-width:1000px}h2{margin-top:40px}summary{cursor:pointer;padding:12px 0}</style><h1>R-Type: corrected saturation weighting</h1><p>Offline previews, fixed palettes per scene, at most 16 playfield colours. No executable or production graphics changed. HUD and dedicated changing pens retained.</p>'+f'<p>The old hybrid compresses counts with a square root and applies a saturation multiplier reaching about 32x. The corrected candidate compresses sprite and tile counts separately with exponent {power:g}, then applies {sprite_weight:g}x sprite priority, and a smooth chroma bonus capped below {1+gain:g}x. It fits original 5-bit arcade colours, not pre-rounded STE inputs. Checker phase here is screen anchored; a game integration should bake it into asset coordinates.</p>'+''.join(cards))
    print(out/'index.html',flush=True)


if __name__=='__main__':main()
