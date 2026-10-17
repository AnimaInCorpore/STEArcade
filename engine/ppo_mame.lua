-- Private synchronous native MAME controller. Bounded step input, no network or traces.
local c=dofile(assert(os.getenv('PPO_CONFIG')))
local m=manager.machine
local cpu=m.devices[':maincpu']
local mem=cpu.spaces.program
local dbg=assert(cpu.debug)
local fields={}
for _,port in pairs(m.ioport.ports) do
 for _,f in pairs(port.fields) do
  if f.player==0 and (f.type==7 or f.type==17 or (f.type>=47 and f.type<=50) or (f.type>=60 and f.type<=62)) then
   fields[f.type]=f
  end
 end
end
assert(fields[7] and fields[17], 'Missing coin/start bindings')
if c.game=='ddragon' then
 for _,port in pairs(m.ioport.ports) do for name,f in pairs(port.fields) do
  if name=='Lives' then f.user_value=0 end
 end end
end
local frame,target= -c.offset,0
local sequence={}
local function pressed(byte,mask,high)
 return mask~=0 and ((high and byte or (~byte))&mask)~=0
end
local function apply()
 local t=sequence[frame] or {c.system_idle,c.p1_idle}
 local s,p=t[1],t[2]
 local values={[17]=pressed(s,c.coin_mask,c.high_system),
  [7]=pressed(c.start_source=='p1' and p or s,c.start_mask,c.start_source=='p1' and c.high_p1 or c.high_system),
  [50]=pressed(p,c.directions[1],c.high_p1),[49]=pressed(p,c.directions[2],c.high_p1),
  [48]=pressed(p,c.directions[3],c.high_p1),[47]=pressed(p,c.directions[4],c.high_p1)}
 for n,b in ipairs(c.buttons) do values[59+n]=pressed(p,b,c.high_p1) end
 if c.game=='ddragon' and frame>=c.boot then values[7]=false end
 for typ,f in pairs(fields) do f:set_value(values[typ] and 1 or 0) end
 if frame>=c.boot then for _,v in ipairs(c.cheats) do mem:write_u8(v[1],v[2]) end end
end
local armed=false
local function arm()
 local first=dbg:bpset(0,'1','g');dbg:bpclear(first)
 for i,a in ipairs(c.candidates) do
  local index=first+i
  assert(dbg:bpset(a,'1',string.format('bpdisable %x;g',index))==index)
 end
 armed=true
end
local function response()
 local pcs={}
 if armed then for index,bp in pairs(dbg:bplist()) do
  if not bp.enabled then pcs[#pcs+1]=bp.address;dbg:bpclear(index) end
 end end
 table.sort(pcs)
 local coverage={}
 for _,a in ipairs(pcs) do coverage[#coverage+1]=string.format('%x',a) end
 local ram={}
 for _,range in ipairs(c.ram) do for a=range[1],range[1]+range[2]-1 do
  ram[#ram+1]=string.format('%02x',mem:read_u8(a))
 end end
 io.stdout:write(string.format('PPO1 %d %s %s\n',frame,table.concat(ram),table.concat(coverage,',')))
 io.stdout:flush()
end
local function command()
 local line=io.stdin:read('*l')
 if not line or line=='quit' then m:exit();return false end
 local n,bytes=line:match('^step (%d+) (%x+)$');n=tonumber(n)
 assert(n and n>=1 and n<=1000 and #bytes==n*4,'Invalid PPO command')
 target=frame+n;sequence={}
 for i=0,n-1 do
  sequence[frame+i]={tonumber(bytes:sub(i*4+1,i*4+2),16),tonumber(bytes:sub(i*4+3,i*4+4),16)}
 end
 apply();return true
end
io.stdout:setvbuf('no')
assert(command())
sub=emu.register_frame_done(function()
 frame=frame+1
 if frame==c.boot then arm() end
 if frame==target then response();if not command() then return end end
 apply()
end)
m.debugger.execution_state='run'
