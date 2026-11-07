#!/usr/bin/env python3
"""Compare returned Atari BOBS*.BMP to saved Hatari reference BMPs.

Usage: python3 dltest_compare.py RETURNED_FOLDER [--reference REF_FOLDER]
Requires Pillow. Never treats a missing file or a size mismatch as a pass.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
from PIL import Image


def compare(actual, reference, out):
    a, b = Image.open(actual).convert('RGB'), Image.open(reference).convert('RGB')
    result = dict(actual=str(actual), reference=str(reference), actual_size=list(a.size), reference_size=list(b.size))
    result['actual_sha256'] = hashlib.sha256(actual.read_bytes()).hexdigest()
    result['reference_sha256'] = hashlib.sha256(reference.read_bytes()).hexdigest()
    if a.size != b.size:
        return dict(result,status='SIZE_MISMATCH')
    ar,br=a.tobytes(),b.tobytes()
    aa=list(zip(ar[::3],ar[1::3],ar[2::3]))
    bb=list(zip(br[::3],br[1::3],br[2::3]))
    coords=[(i%a.width,i//a.width) for i,(x,y) in enumerate(zip(aa,bb)) if x!=y]
    result.update(status='PIXELS_DIFFER' if coords else 'MATCH', changed_pixels=len(coords))
    if coords:
        xs,ys=zip(*coords)
        result['bounding_box']=[min(xs),min(ys),max(xs)+1,max(ys)+1]
        result['first_differences']=[dict(x=x,y=y,actual=aa[y*a.width+x],reference=bb[y*a.width+x]) for x,y in coords[:32]]
        diff=Image.new('RGB',a.size)
        diff.putdata([(255,0,255) if x!=y else tuple(v//4 for v in y) for x,y in zip(aa,bb)])
        path=out/(actual.stem+'_DIFF.png'); diff.save(path)
        result['difference_image']=str(path)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('returned',type=Path)
    parser.add_argument('--reference',type=Path,default=Path(__file__).resolve().parent/'REF')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--machine',choices=['ste','megaste'],default='megaste')
    args=parser.parse_args()
    out=args.out or args.returned/'comparison'; out.mkdir(parents=True,exist_ok=True)
    results=[]
    for prefix,refs in [('BOBS',['HAT8.BMP','HAT16.BMP','HAT16C.BMP']),
                        ('OPEN',['HATO8.BMP','HATO16.BMP','HATO16C.BMP'])]:
        for mode,ref in enumerate(refs):
            if args.machine=='ste' and mode:
                continue
            actual=args.returned/f'{prefix}{mode}.BMP'; reference=args.reference/ref
            if not actual.exists() or not reference.exists():
                results.append(dict(actual=str(actual),reference=str(reference),status='MISSING'))
            else:
                results.append(compare(actual,reference,out))
    report_path=args.returned/'DLTEST.TXT'
    native_report={}
    if report_path.exists():
        text=report_path.read_text(errors='replace')
        native_report=dict(border_opening_confirmed=re.findall(
            r'BORDERS opening confirmed \(1=yes,0=no\): ([0-9A-F]+)',text),
            automatic_failure_groups=re.findall(r'SUMMARY automatic failure groups: ([0-9A-F]+)',text),
            fatal_exception='FATAL unexpected' in text)
    (out/'comparison.json').write_text(json.dumps(dict(images=results,native_report=native_report),indent=2)+'\n')
    for result in results:
        print(f"{result['actual']}: {result['status']} ({result.get('changed_pixels','?')} changed pixels)")
    if '00000000' in native_report.get('border_opening_confirmed',[]):
        print('WARNING: the native report did not confirm open borders in every mode. Matching BMPs do not prove correct scanout.')
    return 0 if all(r['status']=='MATCH' for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
