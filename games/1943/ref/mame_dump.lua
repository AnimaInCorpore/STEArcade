local out = assert(os.getenv('OUT'))
local target = tonumber(os.getenv('FRAME') or '700')
local mem = manager.machine.devices[':maincpu'].spaces['program']
local frame, control, layers = 0, 0, 0
local sprites = string.rep('\0',4096)
local function dump(first,last)
  local data = {}
  for a=first,last do data[#data+1] = string.char(mem:read_u8(a)) end
  return table.concat(data)
end
local function save(name,data)
  local f=assert(io.open(out..'/'..name,'wb'))
  f:write(data)
  f:close()
end
emu.register_frame_done(function()
  frame=frame+1
  if frame~=target then return end
  save('mem.bin',dump(0xd000,0xffff))
  local buffer=emu.item(manager.machine.devices[':spriteram'].items['0/m_buffered'])
  local bytes={}
  for i=0,4095 do bytes[#bytes+1]=string.char(buffer:read(i)) end
  save('sprites.bin',table.concat(bytes))
  local root = manager.machine.devices[':']
  local function item(name) return emu.item(root.items['0/'..name]):read(0) end
  -- Save-state items are authoritative for latches; taps can miss mapped writes.
  control = (item('m_char_on') ~= 0 and 128 or 0) | (item('m_flip_screen_x') ~= 0 and 64 or 0)
  layers = (item('m_bg1_on') ~= 0 and 16 or 0) | (item('m_bg2_on') ~= 0 and 32 or 0) | (item('m_obj_on') ~= 0 and 64 or 0)
  save('regs.bin',string.char(control,layers))
  manager.machine.video:snapshot()
  manager.machine:exit()
end)
