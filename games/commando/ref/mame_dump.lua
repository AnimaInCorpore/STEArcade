local out = assert(os.getenv('OUT'))
local target = tonumber(os.getenv('FRAME') or '700')
local frame = 0
local mem = manager.machine.devices[':maincpu'].spaces['program']
local root = manager.machine.devices[':']
local function item(name) return emu.item(root.items['0/'..name]) end
local function save(name,data)
  local f = assert(io.open(out..'/'..name,'wb')); f:write(data); f:close()
end
local function dump(first,last)
  local bytes={}
  for a=first,last do bytes[#bytes+1]=string.char(mem:read_u8(a)) end
  return table.concat(bytes)
end
local previous=string.rep('\0',384)
emu.register_frame_done(function()
  frame=frame+1
  if frame==target then
    save('mem.bin',dump(0xd000,0xffff))
    save('sprites_previous.bin',previous)
    local regs={}
    for i=0,1 do regs[#regs+1]=string.char(item('m_scroll_x'):read(i)) end
    for i=0,1 do regs[#regs+1]=string.char(item('m_scroll_y'):read(i)) end
    regs[#regs+1]=string.char(item('m_flip_screen_x'):read(0)~=0 and 128 or 0)
    save('regs.bin',table.concat(regs))
    local pal=manager.machine.palettes[':palette']; local bytes={}
    for i=0,255 do
      local v=pal:pen_color(i)
      bytes[#bytes+1]=string.char((v>>16)&255,(v>>8)&255,v&255)
    end
    save('palette.bin',table.concat(bytes))
    manager.machine.video:snapshot(); manager.machine:exit()
  end
  previous=dump(0xfe00,0xff7f)
end)
