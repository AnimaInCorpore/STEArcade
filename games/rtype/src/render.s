; R-Type's renderer: the shared Irem M72 renderer (engine/rt/m72render.s) with R-Type's sizes.  The status bar
; (lines 240-255, a raster split at line 239: FG rows 0-1) gets its own palette when FG covers it.
M72_NTF		= 4096			; FG tiles (rt_b-a*)
M72_NTB		= 4096			; BG tiles (rt_b-b*)
M72_HUD_TOP	= 0
M72_HUD_BOT	= 240
	include	"m72render.s"
