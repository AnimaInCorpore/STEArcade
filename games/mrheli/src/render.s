; Mr. HELI's renderer: the shared Irem M72 renderer (engine/rt/m72render.s) with Mr. HELI's sizes.  The top panel
; (lines 0-31, a raster split at line 31) gets its own palette when FG covers it.
M72_NTF		= 8192			; FG tiles (mh-b-a*)
M72_NTB		= 8192			; BG tiles (b-b*)
M72_HUD_TOP	= 32
M72_HUD_BOT	= 256
	include	"m72render.s"
