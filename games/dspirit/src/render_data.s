
; ======== data (tools/make_render.py appends this) ========

	section data,data
	even
ren_imgs:	dc.l	ren_img0,ren_img1,ren_img2,ren_img3,ren_fimg4,ren_fimg5
ren_msks:	dc.l	ren_msk0,ren_msk1,ren_msk2,ren_msk3,ren_fmsk4,ren_fmsk5
ren_shds:	dc.l	ren_shadow,ren_shadow+2*NSLOT,ren_shadow+4*NSLOT,ren_shadow+6*NSLOT
		dc.l	ren_shadow+8*NSLOT,ren_shadow+8*NSLOT+2*FSLOT
ren_rls:	dc.l	ren_rlist,ren_rlist+512*RL_SIZE,ren_rlist+1024*RL_SIZE,ren_rlist+1536*RL_SIZE
		dc.l	ren_rlist+2048*RL_SIZE,ren_rlist+(2048+PIC_H)*RL_SIZE
ren_rds:	dc.l	ren_rdirty,ren_rdirty+512,ren_rdirty+1024,ren_rdirty+1536,ren_rdirty+2048,ren_rdirty+2048+PIC_H
ren_epoch:	dc.w	1
ren_lab:	incbin	"ren_lab.bin"
ren_q8:		incbin	"ren_q8.bin"
ren_sqrt:	incbin	"ren_sqrt.bin"
	even
ren_chr:	incbin	"ren_chr.bin"
ren_mask:	incbin	"ren_mask.bin"
ren_spr:	incbin	"ren_spr.bin"

	section bss,bss
ren_pictures:	ds.l	1
ren_ntiles:	ds.l	6		; (counters: tiles drawn, run lists built, per layer)
ren_nbuilds:	ds.l	6
ren_skipped:	ds.l	1
ren_choices:	ds.l	1
ren_ch_scene:	ds.l	1		; (the choices: new scenes, palettes that rested on colours that fit worse)
ren_ch_rest:	ds.l	1
ren_vbase:	ds.l	1
ren_bufp:	ds.l	REN_NBUF
ren_dst:	ds.l	1
ren_ck:		ds.l	1
ren_ck_chosen:	ds.l	1
ren_lkey:	ds.l	1
ren_limg:	ds.l	1
ren_lmsk:	ds.l	1
ren_lshd:	ds.l	1
ren_dlo:	ds.w	1		; (a row's damage gathered: its groups, its row; ren_dacc on)
ren_dhi:	ds.w	1
ren_prow:	ds.w	1
ren_dacc:	ds.b	1
	even
ren_l0bank:	ds.w	1		; (layer 0's bank when the colours were chosen; -1: none)
	even
ren_ltile:	ds.l	1
ren_simg:	ds.l	1
ren_ddst:	ds.l	1
ren_lrl:	ds.l	1
ren_lrd:	ds.l	1
ren_rlp:	ds.l	1
ren_ppos:	ds.l	1
ren_pnum:	ds.w	1
ren_prec:	ds.b	1
ren_pfail:	ds.b	1
ren_fdrawn:	ds.b	1
ren_tchg:	ds.b	1
	even
ren_lockset:	ds.l	1		; (the layers locked into layer 0: bits)
ren_vcur:	ds.l	1		; (the buffers' window: ren_view)
ren_dsp:	ds.l	1
ren_tvv:	ds.l	REN_NBUF	; (per buffer: its terrain's scroll, its tag)
ren_tvtag:	ds.l	REN_NBUF
ren_bvoff:	ds.l	REN_NBUF	; (per buffer: its display's offset, its fine scroll)
ren_vmod:	ds.w	1
ren_blast:	ds.w	1
ren_vs:		ds.w	1
ren_xo:		ds.w	1
ren_xadd:	ds.w	1
ren_wmin:	ds.w	1
ren_wmax:	ds.w	1
ren_lb0:	ds.w	1
ren_lbank0:	ds.w	1
ren_td:		ds.w	1
ren_tvs0:	ds.w	1
ren_bkl:	ds.w	1
ren_drow0:	ds.w	1
ren_drows:	ds.w	1
ren_tvs:	ds.w	REN_NBUF
ren_tvok:	ds.b	REN_NBUF
ren_bfine:	ds.b	REN_NBUF
ren_vfine:	ds.b	1
ren_tmode:	ds.b	1
ren_dmgon:	ds.b	1
ren_lockgen:	ds.b	1
	even
ren_trow:	ds.b	VP+1
	even
ren_tdirty:	ds.b	512*REN_NBUF	; (per buffer: layer 0's image rows drawn since its terrain)
ren_dspan:	ds.b	2*SHOWN*REN_NBUF	; (per buffer: the damage of its last picture, per row shown)
ren_tX:		ds.w	1
ren_tk:		ds.w	1
ren_nlock:	ds.w	1
ren_lockl:	ds.w	4
ren_lockdr:	ds.w	4
ren_lockdc:	ds.w	4
ren_lockbank:	ds.b	4
ren_fsrc:	ds.w	PIC_H
ren_lpp:	ds.l	1
ren_bk0:	ds.w	1
ren_bkr:	ds.w	1
ren_bkir:	ds.w	1
ren_bkn:	ds.w	1
ren_slend:	ds.l	1
ren_skey:	ds.l	1
ren_pool_ptr:	ds.l	1
ren_cur:	ds.w	1
ren_vbl_pal:	ds.w	16
ren_bpal:	ds.w	16*REN_NBUF
ren_rmin:	ds.w	1
ren_rmax:	ds.w	1
ren_cmin:	ds.w	1
ren_cmax:	ds.w	1
ren_nlord:	ds.w	1
ren_lord:	ds.b	2*6
ren_ly:		ds.w	1
ren_lbank:	ds.w	1
ren_ltag:	ds.w	1
ren_lb:		ds.w	1
ren_lk:		ds.w	1
ren_lh1:	ds.w	1
ren_pstr:	ds.w	1
ren_ntr:	ds.w	1
ren_tx0:	ds.w	1
ren_ntc:	ds.w	1
ren_kb0:	ds.w	1
ren_ndiff:	ds.w	1
ren_ncent:	ds.w	1
ren_err0:	ds.w	1
ren_qlast:	ds.w	1
ren_nent:	ds.w	1
ren_nbox:	ds.w	1
ren_mm:		ds.w	6
ren_xoffs:	ds.w	1
ren_yoffs:	ds.w	1
ren_sr0:	ds.w	1
ren_sc0:	ds.w	1
ren_ssx:	ds.w	1
ren_ssy:	ds.w	1
ren_scol:	ds.w	1
ren_em1:	ds.w	1
ren_em2:	ds.w	1
ren_em3:	ds.w	1
ren_hrow:	ds.w	1
ren_ctx:	ds.w	1
ren_cty:	ds.w	1
ren_cent:	ds.l	16		; (Oklab L a b of index 1-15)
ren_rep:	ds.w	16		; (the representative pens, -1 none)
ren_box:	ds.l	16
ren_bmtag:	ds.w	8
ren_qtick:	ds.b	1
ren_shown:	ds.b	1
ren_ready:	ds.b	1
ren_prev:	ds.b	1
ren_black:	ds.b	1
ren_wblack:	ds.b	1
ren_allblack:	ds.b	1
ren_scene:	ds.b	1
ren_stable:	ds.b	1
ren_wait:	ds.b	1
ren_spri:	ds.b	1
	even
ren_slst:	ds.b	128*SL
ren_spr_zero:	ds.b	512
ren_sct:	ds.l	16
ren_upk:	ds.b	32
ren_hash:	ds.l	HASH_N
ren_ksum:	ds.l	16*4
ren_cnt:	ds.w	256
ren_sxt:	ds.b	256		; (attr1 -> sizex)
ren_ltab:	ds.l	PIC_H
ren_bmap:	ds.b	8*256
	even
ren_bspread:	ds.l	8*256		; (per bank and pen: its index's spread long, ren_spread)
ren_lut:	ds.b	4096
	even
ren_hist:	ds.w	4096
ren_hpen:	ds.w	4096
ren_ent:	ds.b	NENT_MAX*ENT
ren_tmp:	ds.b	NENT_MAX*ENT
ren_palsnap:	ds.b	$4000
ren_shadow:	ds.w	4*NSLOT+2*FSLOT	; (per layer its tile words as last drawn: layers 0-3 then 4, 5)
ren_shtag:	ds.w	6
ren_lkshd:	ds.w	3*64*64		; (layers 1-3: their tile words when layer 0 was drawn with them locked in)		; (the tag the shadow was drawn with; -1: none)
ren_rlist:	ds.b	(4*512+2*PIC_H)*RL_SIZE	; (the image rows' run lists, their dirty flags)
ren_rdirty:	ds.b	4*512+2*PIC_H
	even
ren_lpar:	ds.b	6*LP		; (the layers' parameters, their full and covered rows)
ren_cacc:	ds.b	PIC_H
ren_img0:	ds.b	IMG_SIZE	; (the layers' images: 4 plane rows a row; their masks, bit 7 = the first column)
ren_img1:	ds.b	IMG_SIZE
ren_img2:	ds.b	IMG_SIZE
ren_img3:	ds.b	IMG_SIZE
ren_fimg4:	ds.b	FIX_SIZE
ren_fimg5:	ds.b	FIX_SIZE
ren_msk0:	ds.b	MSK_SIZE
ren_msk1:	ds.b	MSK_SIZE
ren_msk2:	ds.b	MSK_SIZE
ren_msk3:	ds.b	MSK_SIZE
ren_fmsk4:	ds.b	FMSK_SIZE
ren_fmsk5:	ds.b	FMSK_SIZE
ren_pool:	ds.b	POOL_SIZE
ren_pbufs:	ds.b	2*16*PC_SIZE*PC_MAX	; (the fixed layers' recorded passes: per layer and fine shift)
ren_bufs:	ds.b	BUF_SIZE*REN_NBUF
