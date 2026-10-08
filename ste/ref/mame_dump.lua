-- Ground truth from MAME for the reference renderers: at frame FRAME write the pen colours, a memory
-- range of the main CPU and a screenshot, then quit.  Run with the window (MAME is started with -window;
-- -video none gives no snapshot):
--
--   FRAME=700 OUT=/tmp/dk START=0x6000 END=0x7fff PAL=:palette \
--   mame dkong -window -rompath ../assets/roms -sound none -nothrottle -seconds_to_run 600 \
--        -skip_gameinfo -autoboot_script ref/mame_dump.lua -snapshot_directory /tmp/dk -snapname shot
--
-- writes OUT/pens.txt ("pen rrggbb"), OUT/mem.bin and OUT/shot.png (the snapshot).  The memory and the
-- screenshot are taken after the frame was drawn, so a moving sprite can be one step ahead of the
-- picture: compare several frames (see ref/mame_cmp_dkong.py).  Latches written by the game ($7D82-$7D87)
-- can not be read back reliably from here, the compare tool searches the palette bank instead.
local frame_no = tonumber(os.getenv("FRAME") or "700")
local out = os.getenv("OUT") or "."
local first = tonumber(os.getenv("START") or "0x6000")
local last = tonumber(os.getenv("END") or "0x7fff")
local frame = 0
emu.register_frame_done(function()
  frame = frame + 1
  if frame ~= frame_no then return end
  local m = manager.machine
  local pal = m.palettes[os.getenv("PAL") or ":palette"]
  local f = io.open(out .. "/pens.txt", "w")
  for i = 0, pal.entries - 1 do
    f:write(string.format("%d %06x\n", i, pal:pen_color(i) & 0xffffff))
  end
  f:close()
  local mem = m.devices[os.getenv("CPU") or ":maincpu"].spaces["program"]
  local g = io.open(out .. "/mem.bin", "wb")
  for a = first, last do g:write(string.char(mem:read_u8(a))) end
  g:close()
  m.video:snapshot()
  m:exit()
end)
