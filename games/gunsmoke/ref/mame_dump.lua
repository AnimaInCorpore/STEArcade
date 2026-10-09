local out = assert(os.getenv('OUT'))
local target = tonumber(os.getenv('FRAME') or '700')
local frame = 0
local play = os.getenv('PLAY') == '1'
local mem = manager.machine.devices[':maincpu'].spaces['program']
local root = manager.machine.devices[':']
local function item(name) return emu.item(root.items['0/'..name]) end
local function save(name,data)
 local f=assert(io.open(out..'/'..name,'wb')); f:write(data); f:close()
end
local function dump(first,last)
 local data={}
 for a=first,last do data[#data+1]=string.char(mem:read_u8(a)) end
 return table.concat(data)
end
emu.register_frame_done(function()
 frame=frame+1
 if play then
  local fields=manager.machine.ioport.ports[':SYSTEM'].fields
  fields['Coin 1']:set_value(frame >= 710 and frame < 712 and 1 or 0)
  fields['1 Player Start']:set_value(frame >= 740 and frame < 742 and 1 or 0)
 end
 if frame~=target then return end
 save('mem.bin',dump(0xd000,0xffff))
 local regs={item('m_chon'):read(0) | (item('m_flip_screen_x'):read(0) ~= 0 and 64 or 0),
             item('m_bgon'):read(0) | item('m_objon'):read(0) | item('m_sprite3bank'):read(0)}
 save('regs.bin',string.char(table.unpack(regs)))
 -- Read the actual buffered sprite device, not the CPU's live sprite RAM.
 local dev=manager.machine.devices[':spriteram']
 local data={}
 local buffer=emu.item(dev.items['0/m_buffer'])
 for i=0,4095 do data[#data+1]=string.char(buffer:read(i)) end
 save('sprites.bin',table.concat(data))
 local pal=manager.machine.palettes[':palette']
 local f=assert(io.open(out..'/pens.txt','w'))
 for i=0,639 do f:write(string.format('%d %06x\n',i,pal:pen_color(i)&0xffffff)) end
 f:close()
 manager.machine.video:snapshot()
 manager.machine:exit()
end)
