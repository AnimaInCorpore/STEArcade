; ------------------------------------------------------------------------------
; The renderer (first version: the video set-up and an empty picture; the tile and sprite renderer follows)
; ------------------------------------------------------------------------------

STRIDE = 256				; bytes per line, 512 pixel virtual screen
GAME_X = 24				; byte offset of the game area in a line (3 chunks)
GAME_LINES = 288			; the rotated arcade picture
CROP_TOP = 32
SHOW_OFFSET = CROP_TOP*STRIDE
SCREEN_BYTES = $20000*3

init_video:
	move.l	#screens,d0
	add.l	#$10000-1,d0
	and.l	#$ffff0000,d0
	move.l	d0,bg_address
	add.l	#$20000,d0
	move.l	d0,scr_address
	add.l	#$20000,d0
	move.l	d0,scr_address+4

	move.l	bg_address,d0
	bsr	clear_screen
	move.l	scr_address,d0
	bsr	clear_screen
	move.l	scr_address+4,d0
	bsr	clear_screen

	movem.l	ga_palette,d0-d7
	movem.l	d0-d7,$ffff8240.w

	clr.b	$ffff8260.w		; low resolution, 50 Hz
	move.b	#2,$ffff820a.w
	move.b	#(512-320)/2/2,$ffff820f.w	; virtual line width 512 pixels

	move.l	scr_address+4,draw_screen_address
	move.l	scr_address,display_screen_address
	clr	draw_index
	rts

; d0 = address of a 128 KiB screen

clear_screen:
	move	#2,$ffff8a2e.w
	move	#$ffff,$ffff8a28.w
	move	#$ffff,$ffff8a2a.w
	move	#$ffff,$ffff8a2c.w
	move.b	#1,$ffff8a3a.w		; HOP 1 (halftone only)
	move.b	#0,$ffff8a3b.w		; OP 0 (destination = 0)
	clr.b	$ffff8a3d.w
	move	#2,$ffff8a30.w		; Destination Y increment
	move	#16,$ffff8a36.w		; X count: 16 words, 4096 lines = 128 KB
	move.l	d0,$ffff8a32.w
	move	#4096,$ffff8a38.w
	bra	blit_go			; (the interrupts run: in pieces)

init_render:
	rts

render_frame:
	st	frame_ready
	rts

	borders_handlers
	borders_blit_go
	borders_report
