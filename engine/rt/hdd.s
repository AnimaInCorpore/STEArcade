; Hard disk streaming: the program reads sectors of one data file straight from an ACSI or IDE hard disk while the
; game runs, without TOS (the plan: docs/sprite-preparation.md, "Memory: prepared data from the hard disk"; the
; blueprint: stedaimakaimura's dma_test.s).  Two phases:
;
; hdd_open (TOS still owns the machine: before the port's init_hardware; supervisor mode, interrupts on) finds where
; the file lies on the disk.  It reads the file once through GEMDOS into the scan buffer, with a hook in hdv_rw ($476)
; that logs every sector read GEMDOS makes straight into that buffer.  The log, Getbpb and the AHDI partition table
; (pun_info, $516) give the file's extents: file sector -> physical sector of the drive (both 512 bytes), so a
; fragmented file works up to HDD_EXTENTS pieces.  An IDE drive is then asked for LBA support and its geometry.
;   a0 = the file name, a1 = the scan buffer (even), d0.l = its size  ->  d0.l = 0, or an HDD_E_* code (< 0).
;   The file and the scan buffer must be multiples of 32 KB (the build pads the file): GEMDOS reads a partial
;   logical sector or cluster through its own buffer, which the hook does not see (HDD_E_CACHED).  It takes as
;   long as reading the file.
;
; While the game runs, one request at a time, started by hdd_read and advanced by hdd_poll from the main loop
; (never from the border or VBL handlers):
;   hdd_read: d0.l = the first file sector, d1.l = sectors, a0 = destination (even)  ->  d0.l = 0 (started) or
;             HDD_E_BUSY / HDD_E_RANGE / HDD_E_CLOSED.
;   hdd_poll: -> d0.l = HDD_BUSY (1), 0 (the last request is complete, or none), or an HDD_E_* code (the request
;             is dropped; the next hdd_read may try again).
; A request is split at extent boundaries and into commands of at most HDD_STEP sectors.
;   ACSI: the DMA chip moves the data without the CPU; hdd_poll sends the next command once the last one's interrupt
;         came (MFP GPIP bit 5; the port keeps its MFP interrupt disabled, as all ports do).  Only the six command
;         bytes are waited for (a few microseconds each, at most HDD_SPIN loops).  READ(6): the file must lie
;         below 1 GB of the drive (HDD_E_RANGE at hdd_open).  The floppy is locked out (flock) while a command runs.
;   IDE:  the Falcon's registers at $FFF00000 (and the ST / STE adapters that copy them).  PIO: hdd_poll copies at
;         most HDD_IDE_POLL sectors a call (about 2600 cycles each), when the drive has them ready (alternate
;         status: no wait, and no interrupt line needed); LBA if the drive has it, else the current geometry (CHS).
; Timeouts count pictures: the port's VBL handler runs hdd_vbl (HDD_TIMEOUT VBLs a command, HDD_TIMEOUT a sector).
; hdd_stop (quit, crash: before the hardware is given back) finishes a command in flight, so TOS's driver finds the
; drive idle.  Every routine keeps every register but d0.
;
; The port places hdd_text in its text and hdd_vars in its bss; the destination must be ST-RAM (all of the STE's).
; tools/hddtest.sh checks it in Hatari (ACSI and IDE images, EmuTOS's own drivers); engine/hdd_test.py checks
; hdd_read / hdd_poll against models of the DMA chip and an IDE drive.

	ifnd	HDD_EXTENTS
HDD_EXTENTS = 64			; file pieces (12 bytes each)
	endc
	ifnd	HDD_STEP
HDD_STEP = 128				; sectors a command (64 KB)
	endc
	ifnd	HDD_IDE_POLL
HDD_IDE_POLL = 2			; IDE sectors copied a hdd_poll
	endc
	ifnd	HDD_TIMEOUT
HDD_TIMEOUT = 100			; VBLs (2 s)
	endc
HDD_SPIN = 20000			; busy-wait loops (~0.1 s) for a command byte or a drive to become ready
HDD_LOG = 64				; hdv_rw calls logged per scan buffer

HDD_BUSY = 1
HDD_E_OPEN = -1				; Fopen failed
HDD_E_READ = -2				; Fread failed, or the file is empty
HDD_E_DRIVE = -3			; not on an ACSI / IDE drive of an AHDI compatible driver (pun_info)
HDD_E_CACHED = -4			; part of the file came through GEMDOS's buffer: pad the file to 32 KB
HDD_E_FRAGMENTED = -5			; more than HDD_EXTENTS pieces (or HDD_LOG reads in one scan buffer)
HDD_E_RANGE = -6			; beyond the file, or beyond what the command can address
HDD_E_IDE = -7				; IDENTIFY failed
HDD_E_TIMEOUT = -8
HDD_E_STATUS = -9			; the drive reported an error
HDD_E_BUSY = -10			; a request is in flight
HDD_E_CLOSED = -11			; no hdd_open succeeded

HDD_ACSI = 1				; hdd_kind
HDD_IDE = 2

HDD_ST_ACSI = 1				; hdd_state
HDD_ST_IDE = 2

DMA_DATA = $ffff8604			; (word: FDC / ACSI data, sector count)
DMA_MODE = $ffff8606			; (word: mode written, status read)
FLOCK = $43e

IDE_DATA = $fff00000
IDE_COUNT = $fff00009
IDE_SECTOR = $fff0000d
IDE_CYL_LO = $fff00011
IDE_CYL_HI = $fff00015
IDE_HEAD = $fff00019
IDE_STATUS = $fff0001d			; (read: acknowledges the interrupt; write: the command)
IDE_ALT = $fff00039			; (read: the status, nothing acknowledged)

; In the port's VBL handler.
hdd_vbl	macro
	tst	hdd_ticks
	beq.s	.z\@
	subq	#1,hdd_ticks
.z\@:
	endm

hdd_text macro

; ---------------------------------------------------------------------------------------------- TOS phase

hdd_open:
	movem.l	d1-d7/a0-a6,-(sp)
	move.l	a1,hdd_scan
	move.l	d0,hdd_scan_size
	clr.b	hdd_kind
	clr.b	hdd_state
	clr	hdd_extent_count
	clr.l	hdd_sectors
	move	#-1,hdd_dev

	clr	-(sp)			; Fopen (read)
	move.l	a0,-(sp)
	move	#$3d,-(sp)
	trap	#1
	addq	#8,sp
	moveq	#HDD_E_OPEN,d6
	tst.l	d0
	bmi	.out\@
	move	d0,d5			; the handle
	moveq	#0,d4			; the file sector at the scan buffer's start

	move.l	$476.w,hdd_old_rw
	move.l	#hdd_hook,$476.w

.chunk\@:
	clr	hdd_log_count
	sf	hdd_log_full
	move.l	hdd_scan,-(sp)		; Fread
	move.l	hdd_scan_size,-(sp)
	move	d5,-(sp)
	move	#$3f,-(sp)
	trap	#1
	lea	12(sp),sp
	moveq	#HDD_E_READ,d6
	tst.l	d0
	bmi.s	.close\@
	move.l	d0,d3			; bytes read
	bsr	hdd_map_log
	tst.l	d6
	bne.s	.close\@
	move.l	d3,d0
	add.l	#511,d0
	moveq	#9,d1
	lsr.l	d1,d0
	add.l	d0,d4			; the file's sectors so far
	cmp.l	hdd_scan_size,d3
	beq.s	.chunk\@		; (a full buffer: there may be more)

	moveq	#HDD_E_READ,d6
	tst.l	d4
	beq.s	.close\@
	moveq	#HDD_E_CACHED,d6
	cmp.l	hdd_sectors,d4		; every sector seen by the hook?
	bne.s	.close\@
	moveq	#0,d6

.close\@:
	move.l	hdd_old_rw,$476.w
	move	d5,-(sp)		; Fclose
	move	#$3e,-(sp)
	trap	#1
	addq	#4,sp

	tst.l	d6
	bne.s	.out\@
	cmp.b	#HDD_IDE,hdd_kind
	bne.s	.out\@
	bsr	hdd_identify

.out\@:
	tst.l	d6
	beq.s	.ok\@
	clr.b	hdd_kind		; (hdd_read: HDD_E_CLOSED)
.ok\@:
	move.l	d6,d0
	movem.l	(sp)+,d1-d7/a0-a6
	rts

; The hdv_rw hook: logs a read into the scan buffer (16 bytes from 4(sp): rwflag.w, buf.l, count.w, recno.w,
; dev.w, lrecno.l), then goes on to the driver.  d0-d2 / a0-a2 are scratch for an hdv_rw routine.
hdd_hook:
	move	4(sp),d0
	and	#9,d0			; a write, or physical mode
	bne.s	.chain\@
	move.l	6(sp),d0
	sub.l	hdd_scan,d0
	cmp.l	hdd_scan_size,d0	; (unsigned: below the buffer is far above)
	bhs.s	.chain\@
	move	hdd_log_count,d0
	cmp	#HDD_LOG,d0
	bhs.s	.full\@
	addq	#1,hdd_log_count
	lsl	#4,d0
	lea	hdd_log,a0
	add	d0,a0
	movem.l	4(sp),d0-d2/a1
	movem.l	d0-d2/a1,(a0)
	bra.s	.chain\@
.full\@:
	st	hdd_log_full
.chain\@:
	move.l	hdd_old_rw,-(sp)
	rts

; The log of one scan buffer into extents.  d4 = the file sector at the buffer's start  ->  d6 = 0 or HDD_E_*.
; The reads must cover the file without a gap, in order (hdd_sectors: the sectors covered so far).
hdd_map_log:
	movem.l	d0-d5/a0-a3,-(sp)
	moveq	#HDD_E_FRAGMENTED,d6
	tst.b	hdd_log_full
	bne	.out\@
	lea	hdd_log,a2
	move	hdd_log_count,d5
	bra	.next\@

.record\@:
	move	10(a2),d0		; dev
	cmp	hdd_dev,d0
	beq.s	.same\@
	moveq	#HDD_E_DRIVE,d6
	tst	hdd_dev
	bpl	.out\@			; (another drive in the middle of the file)
	bsr	hdd_drive
	tst.l	d6
	bne	.out\@
.same\@:
	moveq	#0,d1
	move	8(a2),d1		; recno
	cmp	#-1,d1
	bne.s	.short\@
	move.l	12(a2),d1		; lrecno
.short\@:
	moveq	#0,d2
	move	6(a2),d2		; count
	move	hdd_shift,d0		; logical -> physical sectors
	lsl.l	d0,d1
	lsl.l	d0,d2
	add.l	hdd_part,d1		; + the partition's start

	moveq	#HDD_E_CACHED,d6
	move.l	2(a2),d0		; buf
	sub.l	hdd_scan,d0
	move	d0,d3
	and	#511,d3
	bne	.out\@
	moveq	#9,d3
	lsr.l	d3,d0
	add.l	d4,d0			; the file sector
	cmp.l	hdd_sectors,d0		; right after the sectors covered so far?
	bne	.out\@
	add.l	d2,hdd_sectors

	moveq	#HDD_E_RANGE,d6
	cmp.b	#HDD_ACSI,hdd_kind
	bne.s	.addressable\@
	move.l	d1,d3
	add.l	d2,d3
	cmp.l	#$200000,d3		; READ(6): 21 bits
	bhi	.out\@
.addressable\@:

	lea	hdd_extents,a3		; d0 = file sector, d1 = physical sector, d2 = sectors
	move	hdd_extent_count,d3
	beq.s	.new\@
	subq	#1,d3
	mulu	#12,d3
	add.l	d3,a3			; the last extent
	move.l	4(a3),d3
	add.l	8(a3),d3
	cmp.l	d1,d3			; continues it on the disk?
	bne.s	.add\@
	add.l	d2,8(a3)
	bra.s	.done\@
.add\@:
	lea	12(a3),a3
.new\@:
	moveq	#HDD_E_FRAGMENTED,d6
	cmp	#HDD_EXTENTS,hdd_extent_count
	bhs.s	.out\@
	addq	#1,hdd_extent_count
	movem.l	d0-d2,(a3)
.done\@:
	lea	16(a2),a2
.next\@:
	dbf	d5,.record\@
	moveq	#0,d6
.out\@:
	movem.l	(sp)+,d0-d5/a0-a3
	rts

; The file's drive: d0 = BIOS device  ->  hdd_dev, hdd_shift, hdd_part, hdd_kind, hdd_unit; d6 = 0 or HDD_E_DRIVE.
hdd_drive:
	movem.l	d0-d5/a0-a2,-(sp)
	move	d0,d3
	move	d0,hdd_dev
	moveq	#HDD_E_DRIVE,d6
	cmp	#16,d3
	bhs	.out\@

	move	d3,-(sp)		; Getbpb
	move	#7,-(sp)
	trap	#13
	addq	#4,sp
	tst.l	d0
	beq	.out\@
	move.l	d0,a0
	move	(a0),d1			; recsiz
	moveq	#0,d2
.shift\@:
	cmp	#512,d1			; log2(recsiz / 512)
	beq.s	.shifted\@
	blo.s	.out\@			; (not a power of 2)
	lsr	#1,d1
	addq	#1,d2
	bra.s	.shift\@
.shifted\@:
	move	d2,hdd_shift

	move.l	$516.w,d0		; pun_ptr
	beq.s	.out\@
	move.l	d0,a0
	cmp.l	#'AHDI',2+16+16*4(a0)	; P_cookie
	bne.s	.out\@
	move.b	2(a0,d3.w),d1		; pun[dev]
	bmi.s	.out\@			; (not the hard disk driver's)
	move	d3,d0
	lsl	#2,d0
	move.l	2+16(a0,d0.w),hdd_part	; part_start[dev]
	moveq	#7,d0
	and.b	d1,d0
	move.b	d0,hdd_unit
	and.b	#$38,d1			; bit 3 SCSI, bit 4 IDE, bit 5 USB
	beq.s	.acsi\@
	cmp.b	#$10,d1
	bne.s	.out\@			; (SCSI, USB: not on the STE)
	move.b	#HDD_IDE,hdd_kind
	bra.s	.ok\@
.acsi\@:
	move.b	#HDD_ACSI,hdd_kind
.ok\@:
	moveq	#0,d6
.out\@:
	movem.l	(sp)+,d0-d5/a0-a2
	rts

; IDENTIFY (TOS's 200 Hz clock for the timeouts; the answer into the scan buffer)  ->  hdd_lba, hdd_heads, hdd_spt;
; d6 = 0 or HDD_E_IDE.
hdd_identify:
	movem.l	d0-d2/a0-a1,-(sp)
	moveq	#HDD_E_IDE,d6
	move.b	hdd_unit,d0
	lsl.b	#4,d0
	or.b	#$a0,d0
	move.b	d0,IDE_HEAD
	move.b	#$80,d1			; not BSY
	moveq	#0,d2
	bsr	hdd_ide_wait_tos
	bne	.out\@
	move.b	#$ec,IDE_STATUS
	move.b	#$89,d1			; DRQ, not BSY or ERR
	moveq	#$08,d2
	bsr	hdd_ide_wait_tos
	bne.s	.out\@
	tst.b	IDE_STATUS
	lea	IDE_DATA,a0
	move.l	hdd_scan,a1
	moveq	#512/4-1,d0
.copy\@:
	move.l	(a0),(a1)+
	dbf	d0,.copy\@

	move.l	hdd_scan,a0
	btst	#1,49*2(a0)		; word 49 bit 9: LBA
	sne	hdd_lba
	move	3*2(a0),hdd_heads	; the default geometry
	move	6*2(a0),hdd_spt
	btst	#0,53*2+1(a0)		; word 53 bit 0: words 54-58 (the current geometry) valid
	beq.s	.geometry\@
	move	55*2(a0),hdd_heads
	move	56*2(a0),hdd_spt
.geometry\@:
	moveq	#0,d6
	tst.b	hdd_lba
	bne.s	.out\@
	moveq	#HDD_E_IDE,d6
	tst	hdd_heads
	beq.s	.out\@
	tst	hdd_spt
	beq.s	.out\@
	moveq	#0,d6
.out\@:
	movem.l	(sp)+,d0-d2/a0-a1
	rts

; d1.b = mask, d2.b = value: Z set when (alternate status & mask) = value within 2 s.
hdd_ide_wait_tos:
	movem.l	d0/d3,-(sp)
	move.l	$4ba.w,d0		; _hz_200
	add.l	#2*200,d0
.loop\@:
	move.b	IDE_ALT,d3
	and.b	d1,d3
	cmp.b	d2,d3
	beq.s	.out\@
	cmp.l	$4ba.w,d0
	bhi.s	.loop\@
	andi.b	#$fb,ccr		; (timeout: Z clear)
.out\@:
	movem.l	(sp)+,d0/d3		; (movem keeps the flags)
	rts

; ---------------------------------------------------------------------------------------------- while the game runs

hdd_read:
	movem.l	d1-d2,-(sp)
	moveq	#HDD_E_CLOSED,d2
	tst.b	hdd_kind
	beq.s	.out\@
	moveq	#HDD_E_BUSY,d2
	tst.b	hdd_state
	bne.s	.out\@
	moveq	#HDD_E_RANGE,d2
	tst.l	d1
	beq.s	.out\@
	move.l	d0,hdd_req_sector
	move.l	d1,hdd_req_count
	add.l	d0,d1
	bcs.s	.out\@
	cmp.l	hdd_sectors,d1
	bhi.s	.out\@
	move.l	a0,hdd_req_dest
	bsr	hdd_step
	move.l	d0,d2
.out\@:
	move.l	d2,d0
	movem.l	(sp)+,d1-d2
	rts

hdd_poll:
	moveq	#0,d0
	move.b	hdd_state,d0
	beq.s	.out\@
	cmp.b	#HDD_ST_IDE,d0
	beq	hdd_poll_ide

	btst	#5,$fffffa01.w		; ACSI: the command's interrupt (active low)?
	beq.s	.done\@
	moveq	#HDD_BUSY,d0
	tst	hdd_ticks
	bne.s	.out\@
	bsr	hdd_acsi_release
	moveq	#HDD_E_TIMEOUT,d0
	bra.s	.out\@
.done\@:
	move.l	d1,-(sp)
	move	#$008a,DMA_MODE.w
	move	DMA_DATA.w,d0		; the status byte
	move	DMA_MODE.w,d1		; the DMA status: bit 0 = no error
	bsr	hdd_acsi_release
	and	#$ff,d0
	bne.s	.error\@
	btst	#0,d1
	beq.s	.error\@
	move.l	(sp)+,d1
	move	hdd_step_left,d0
	bra	hdd_advance
.error\@:
	move.l	(sp)+,d1
	moveq	#HDD_E_STATUS,d0
.out\@:
	rts

hdd_poll_ide:
	movem.l	d1/a0-a1,-(sp)
	moveq	#HDD_IDE_POLL-1,d1
	move.l	hdd_ide_dest,a1
.sector\@:
	move.b	IDE_ALT,d0
	bmi.s	.not_ready\@		; BSY
	btst	#0,d0			; ERR
	bne.s	.error\@
	btst	#3,d0			; DRQ
	beq.s	.not_ready\@
	tst.b	IDE_STATUS		; (acknowledges the interrupt)
	lea	IDE_DATA,a0
	moveq	#512/32-1,d0
.copy\@:
	rept	8
	move.l	(a0),(a1)+
	endr
	dbf	d0,.copy\@
	move.l	a1,hdd_ide_dest
	move	#HDD_TIMEOUT,hdd_ticks
	subq	#1,hdd_step_left
	beq.s	.step_done\@
	tst.b	IDE_ALT			; (the status is valid 400 ns after the data)
	dbf	d1,.sector\@
	moveq	#HDD_BUSY,d0
	bra.s	.out\@

.not_ready\@:
	moveq	#HDD_BUSY,d0
	tst	hdd_ticks
	bne.s	.out\@
	clr.b	hdd_state
	moveq	#HDD_E_TIMEOUT,d0
	bra.s	.out\@
.error\@:
	tst.b	IDE_STATUS
	clr.b	hdd_state
	moveq	#HDD_E_STATUS,d0
	bra.s	.out\@
.step_done\@:
	move	hdd_step_count,d0
	movem.l	(sp)+,d1/a0-a1
	bra.s	hdd_advance
.out\@:
	movem.l	(sp)+,d1/a0-a1
	rts

; The command of d0.w sectors is complete: on to the rest of the request.  ->  d0.l = 0, HDD_BUSY or HDD_E_*.
hdd_advance:
	move.l	d1,-(sp)
	clr.b	hdd_state
	moveq	#0,d1
	move	d0,d1
	add.l	d1,hdd_req_sector
	sub.l	d1,hdd_req_count
	lsl.l	#8,d1
	add.l	d1,d1
	add.l	d1,hdd_req_dest
	move.l	(sp)+,d1
	moveq	#0,d0
	tst.l	hdd_req_count
	beq.s	.out\@
	bsr	hdd_step
	tst.l	d0
	bne.s	.out\@
	moveq	#HDD_BUSY,d0
.out\@:
	rts

; Starts the command for the request's next piece: up to HDD_STEP sectors inside one extent.  ->  d0.l = 0 or HDD_E_*.
hdd_step:
	movem.l	d1-d4/a0,-(sp)
	move.l	hdd_req_sector,d0
	lea	hdd_extents,a0
	move	hdd_extent_count,d4
	subq	#1,d4
.find\@:
	move.l	d0,d1
	sub.l	(a0),d1			; the sector's offset in the extent
	cmp.l	8(a0),d1		; (unsigned: before the extent is far above)
	blo.s	.found\@
	lea	12(a0),a0
	dbf	d4,.find\@
	moveq	#HDD_E_RANGE,d0
	bra	.out\@
.found\@:
	move.l	8(a0),d2
	sub.l	d1,d2			; the extent's sectors from there
	add.l	4(a0),d1		; the physical sector
	cmp.l	hdd_req_count,d2
	bls.s	.c1\@
	move.l	hdd_req_count,d2
.c1\@:
	cmp.l	#HDD_STEP,d2
	bls.s	.c2\@
	move.l	#HDD_STEP,d2
.c2\@:
	move	d2,hdd_step_count
	move	d2,hdd_step_left
	move	#HDD_TIMEOUT,hdd_ticks
	cmp.b	#HDD_IDE,hdd_kind
	beq	.ide\@

	move	#1,FLOCK.w		; ACSI: READ(6) of d2 sectors from d1 (21 bits: hdd_open checked)
	move.l	hdd_req_dest,d0
	move.b	d0,$ffff860d.w
	lsr.l	#8,d0
	move.b	d0,$ffff860b.w
	lsr.l	#8,d0
	move.b	d0,$ffff8609.w
	move	#$0190,DMA_MODE.w	; (toggling the direction clears the FIFO)
	move	#$0090,DMA_MODE.w
	move	d2,DMA_DATA.w		; the DMA's sector count
	move	#$0088,DMA_MODE.w
	move.b	hdd_unit,d0
	lsl.b	#5,d0
	or.b	#$08,d0			; target << 5 | READ(6)
	bsr	hdd_acsi_byte
	bne.s	.timeout\@
	move.l	d1,d0
	swap	d0
	and	#$1f,d0
	bsr	hdd_acsi_byte
	bne.s	.timeout\@
	move	d1,d0
	lsr	#8,d0
	bsr	hdd_acsi_byte
	bne.s	.timeout\@
	move	d1,d0
	bsr	hdd_acsi_byte
	bne.s	.timeout\@
	move	d2,d0
	bsr	hdd_acsi_byte
	bne.s	.timeout\@
	move.l	#$00000000,DMA_DATA.w	; control byte 0; mode 0 starts the DMA
	move.b	#HDD_ST_ACSI,hdd_state
	moveq	#0,d0
	bra	.out\@
.timeout\@:
	bsr	hdd_acsi_release
	moveq	#HDD_E_TIMEOUT,d0
	bra	.out\@

.ide\@:
	move.l	hdd_req_dest,hdd_ide_dest
	move.b	hdd_unit,d4
	lsl.b	#4,d4
	tst.b	hdd_lba
	beq.s	.chs\@
	move.l	d1,d0			; LBA: bits 0-7 sector, 8-23 cylinder, 24-27 head
	rol.l	#8,d0
	and.b	#$0f,d0
	or.b	#$e0,d0
	or.b	d0,d4
	move.l	d1,d3			; (sector, cylinder low, cylinder high: d3 bytes 0, 1, 2)
	bra.s	.registers\@
.chs\@:
	move	hdd_heads,d3
	mulu	hdd_spt,d3		; sectors a cylinder
	move.l	d1,d0
	divu	d3,d0			; remainder : cylinder
	bvs.s	.range\@
	move	d0,d3
	lsl.l	#8,d3			; (cylinder into bytes 1, 2)
	clr	d0
	swap	d0
	divu	hdd_spt,d0		; sector : head
	or.b	d0,d4
	or.b	#$a0,d4
	swap	d0
	addq	#1,d0
	move.b	d0,d3			; (sector, from 1, into byte 0)
.registers\@:
	move.b	d4,IDE_HEAD
	move	#HDD_SPIN,d0
.ready\@:
	tst.b	IDE_ALT			; BSY?
	bpl.s	.go\@
	dbf	d0,.ready\@
	moveq	#HDD_E_TIMEOUT,d0
	bra.s	.out\@
.go\@:
	move.b	d2,IDE_COUNT
	move.b	d3,IDE_SECTOR
	lsr.l	#8,d3
	move.b	d3,IDE_CYL_LO
	lsr.l	#8,d3
	move.b	d3,IDE_CYL_HI
	move.b	#$20,IDE_STATUS		; READ SECTORS
	move.b	#HDD_ST_IDE,hdd_state
	moveq	#0,d0
	bra.s	.out\@
.range\@:
	moveq	#HDD_E_RANGE,d0
.out\@:
	movem.l	(sp)+,d1-d4/a0
	rts

; d0.b = a command byte: written with A1 high next  ->  Z set when the target took it (at most HDD_SPIN loops).
hdd_acsi_byte:
	and.l	#$ff,d0
	swap	d0
	move	#$008a,d0
	move.l	d0,DMA_DATA.w
	move.l	#HDD_SPIN,d0
.wait\@:
	btst	#5,$fffffa01.w
	beq.s	.out\@			; (Z set)
	subq.l	#1,d0
	bne.s	.wait\@
	moveq	#1,d0			; (Z clear)
.out\@:
	rts

; The DMA chip back to the floppy.
hdd_acsi_release:
	move	#$0080,DMA_MODE.w
	clr	FLOCK.w
	clr.b	hdd_state
	rts

; Quit / crash: lets a command in flight finish (busy-waits: the VBL may be off).
hdd_stop:
	movem.l	d0-d2/a0,-(sp)
	move.b	hdd_state,d0
	beq.s	.out\@
	cmp.b	#HDD_ST_IDE,d0
	beq.s	.ide\@
	move.l	#HDD_SPIN*40,d0		; ACSI: the data phase may take ~0.1 s
.acsi\@:
	btst	#5,$fffffa01.w
	beq.s	.acsi_done\@
	subq.l	#1,d0
	bne.s	.acsi\@
.acsi_done\@:
	move	#$008a,DMA_MODE.w
	tst	DMA_DATA.w
	bsr	hdd_acsi_release
	bra.s	.out\@
.ide\@:
	move	hdd_step_left,d1	; IDE: reads the rest of the command away
	subq	#1,d1
.sector\@:
	move.l	#HDD_SPIN*10,d2
.wait\@:
	move.b	IDE_ALT,d0
	bmi.s	.busy\@
	btst	#0,d0
	bne.s	.ide_done\@
	btst	#3,d0
	bne.s	.drain\@
.busy\@:
	subq.l	#1,d2
	bne.s	.wait\@
	bra.s	.ide_done\@
.drain\@:
	tst.b	IDE_STATUS
	lea	IDE_DATA,a0
	moveq	#512/4-1,d0
.word\@:
	tst.l	(a0)
	dbf	d0,.word\@
	dbf	d1,.sector\@
.ide_done\@:
	tst.b	IDE_STATUS
	clr.b	hdd_state
.out\@:
	movem.l	(sp)+,d0-d2/a0
	rts

	endm

hdd_vars macro
	even
hdd_sectors:	ds.l	1		; the file's size in 512-byte sectors
hdd_part:	ds.l	1		; the partition's first physical sector
hdd_req_sector:	ds.l	1		; the request: next file sector, sectors left, next destination
hdd_req_count:	ds.l	1
hdd_req_dest:	ds.l	1
hdd_ide_dest:	ds.l	1		; IDE: the next sector of the command in flight
hdd_scan:	ds.l	1
hdd_scan_size:	ds.l	1
hdd_old_rw:	ds.l	1
hdd_ticks:	ds.w	1		; VBLs left for the command / sector in flight (hdd_vbl)
hdd_step_count:	ds.w	1		; sectors of the command in flight, of them still to come
hdd_step_left:	ds.w	1
hdd_extent_count: ds.w	1
hdd_heads:	ds.w	1		; IDE without LBA: the geometry
hdd_spt:	ds.w	1
hdd_dev:	ds.w	1		; the BIOS device (hdd_open)
hdd_shift:	ds.w	1		; log2(logical sector / 512)
hdd_log_count:	ds.w	1
hdd_kind:	ds.b	1		; 0 (closed), HDD_ACSI, HDD_IDE
hdd_unit:	ds.b	1		; ACSI target, IDE master 0 / slave 1
hdd_lba:	ds.b	1
hdd_state:	ds.b	1		; 0 (idle), HDD_ST_ACSI, HDD_ST_IDE: a command in flight
hdd_log_full:	ds.b	1
	even
hdd_extents:	ds.l	3*HDD_EXTENTS	; file sector, physical sector, sectors
hdd_log:	ds.b	16*HDD_LOG	; hdd_open's hdv_rw log
	endm
