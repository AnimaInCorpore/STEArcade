; The picture: not written yet (the next step of the port, see README.md "Next steps").  The runtime calls these three.

init_render:				; once, before the program starts
	rts

vbl_video:				; in the VBL: show a finished picture
	rts

render_frame:				; at the hook, when a picture is due: draw the arcade frame (cell_list, the sprites)
	clr.b	tiles_all
	move.l	#cell_list,cell_ptr
	rts
