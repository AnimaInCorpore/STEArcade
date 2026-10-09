local out = assert(os.getenv('OUT'))
local target = tonumber(os.getenv('FRAME') or '700')
local frame = 0
local regs = {}
for i=0,15 do regs[i] = 0 end
local mem = manager.machine.devices[':maincpu'].spaces['program']
local ports = manager.machine.devices[':maincpu'].spaces['io']
local root = manager.machine.devices[':']
local function item(name) return emu.item(root.items['0/'..name]) end
local prev = string.rep('\0', 512)
local function dump(first,last)
  local data = {}
  for a=first,last do data[#data+1] = string.char(mem:read_u8(a)) end
  return table.concat(data)
end
local function save(name, data)
  local f = assert(io.open(out..'/'..name, 'wb'))
  f:write(data)
  f:close()
end
emu.register_frame_done(function()
  frame = frame + 1
  if frame == target then
    regs[13] = item('m_scroll_bank'):read(0) // 4096
    regs[4] = (item('m_chon'):read(0) == 0 and 128 or 0) | (item('m_flip_screen_x'):read(0) ~= 0 and 64 or 0)
    regs[12] = (item('m_bgon'):read(0) == 0 and 2 or 0) | (item('m_objon'):read(0) == 0 and 4 or 0)
    regs[14] = item('m_screen_layout'):read(0)
    for i=0,1 do
      regs[8+i] = item('m_scroll_x'):read(i)
      regs[10+i] = item('m_scroll_y'):read(i)
    end
    local bank = regs[13]
    local saved = {}
    for i=0,15 do saved[i] = regs[i] end
    save('mem.bin',dump(0xd000,0xffff))
    save('sprites_previous.bin',prev)
    local bg = {}
    for b=0,3 do
      ports:write_u8(13,b)
      bg[#bg+1] = dump(0xc000,0xcfff)
    end
    ports:write_u8(13,bank)
    save('bg.bin',table.concat(bg))
    local bytes = {}
    for i=0,15 do bytes[#bytes+1] = string.char(saved[i]) end
    save('regs.bin',table.concat(bytes))
    local pal = manager.machine.palettes[':palette']
    local f = assert(io.open(out..'/pens.txt','w'))
    for i=0,1023 do f:write(string.format('%d %06x\n',i,pal:pen_color(i)&0xffffff)) end
    f:close()
    manager.machine.video:snapshot()
    manager.machine:exit()
  end
  prev = dump(0xfe00,0xffff)
end)
