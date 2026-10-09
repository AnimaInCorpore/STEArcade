"""Translate Commando's complete fixed ROM, retaining separate operand bytes."""
from pathlib import Path
import sys,pickle,json
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'engine'))
import z80x,z80dis
from translate import compile_code
from machine import Program,BUILD
IDLE=0x8001
TOKEN=0xc7fe


def discover(img,roots,known,tables=None):
    """tables: a set that gets the targets of the RST 30 word tables (entered by a computed jump: joins)"""
    code={};work=list(roots)
    while work:
        pc=work.pop()
        while 0<=pc<len(img) and pc not in code:
            i=z80dis.decode(img,pc);code[pc]=i;nxt=pc+i.length
            if i.flow in ('jmp','jcc','call','ccall','rst'):
                work.append(i.target)
            if i.flow=='rst' and i.target==0x30:
                # RST 30 pops the return address and indexes the following word table.
                end=len(img);a=nxt
                while a+1<end and a not in known:
                    target=img[a]|(img[a+1]<<8)
                    if not 0x100<=target<len(img):break
                    work.append(target)
                    if tables is not None:tables.add(target)
                    if target>=nxt:end=min(end,target)
                    a+=2
                break
            if i.flow in ('jmp','ret','ijmp','halt'):break
            pc=nxt
    return code


class Emitter(z80x.Emitter):
    def __init__(self,*a,buffer_sites=(),**k):
        super().__init__(*a,**k);self.buffer_sites=set(buffer_sites)
    def emit_ins(self,pc,*a,**k):
        super().emit_ins(pc,*a,**k)
        if pc in self.buffer_sites:self.e('bsr buffer_sprites')
    def x_ld_i_a(self,ins):self.e('move.b d0,g1_ireg')
    def _incdec(self,ins,op):
        if self.lo & z80x.H and ins.ops[0]==('r8','a'):
            self.e('move.w d0,-(sp)')
            old=self.lo;self.lo &=~z80x.H
            super()._incdec(ins,op);self.lo=old
            self.e('move.w (sp)+,d7');self.e('and.w #15,d7')
            self.e('bclr #5,d6')
            label=self.new_label()
            self.e('cmp.w #%d,d7' % (15 if op=='addq' else 0))
            self.e('bne.s '+label);self.e('bset #5,d6');self.lines.append(label+':')
        else:super()._incdec(ins,op)


def generate():
    img=Program()
    baseline=json.loads((Path(__file__).resolve().parents[1]/'docs/coverage.json').read_text())
    known=set(baseline['pcs']);sites=set(baseline['buffer_sites'])
    for f in BUILD.glob('cover_*.pkl'):
        d=pickle.loads(f.read_bytes());known|=d['pcs']
        sites|={pc for pc,a in d['writes'] if a==0xc806}
    cfg=z80x.Config(prefix='Z',table='z80_dispatch',token_sym='z80_irq_ret',mode='signed',
                    block=65536,iyaddr=0xc7f0,fshadow=0xc7f2,io_read_redirect={},
                    write_hooks=[],nmi_token=TOKEN,table_entries=0xc000,rst28_tables=False,
                    iff_sym='g_iff',bit_s=True,**z80x.FAST)
    tables=set()
    code=discover(img,[0,8,16]+sorted(known),known,tables)
    # All direct stores to the sprite buffer latch, plus indirect sites from coverage.
    sites|={pc for pc,i in code.items() if i.mn=='ld' and i.ops[0]==('ind16',0xc806)}
    hooks={IDLE}
    # the entries: reset and interrupts, the idle hook, the RST 30 table targets (compile_code adds the return
    # points and the code addresses the program holds as numbers)
    joins={0,8,16,IDLE}|tables
    em=compile_code(code,joins,cfg,hooks,emitter=Emitter,ijmp_flags=True,flags_at=hooks,buffer_sites=sites)
    executed_unsupported=[u for u in em.unsupported if u[0] in known]
    if executed_unsupported:
        raise RuntimeError(f'Observed instructions cannot be translated: {executed_unsupported}')
    out=['; generated Commando World Z80 -> 68000','\tsection text,code']+em.lines
    missing=sorted(p for p in em.refs if p not in code)
    for p in missing:out.append(f'Z{p:04X}: move.w #${p:04X},d7\n\tjmp z80_badpc')
    out+=['\tsection data,data','\tcnop 0,2','z80_entries:']
    for p in sorted(code):
        if p not in em.no_entry:out.append(f'\tdc.w ${p:04X}\n\tdc.l Z{p:04X}')   # (merged: z80_badpc)
    out.append(f'\tdc.w ${TOKEN:04X}\n\tdc.l z80_irq_ret\n\tdc.w $FFFF')
    return '\n'.join(out)+'\n',em,code,missing

if __name__=='__main__':
    text,em,code,missing=generate();(BUILD/'code_commando.s').write_text(text)
    print('instructions',len(code),'unsupported',em.unsupported,'missing',missing)
