; RetroNix TRS-80 Model 4 machine image: relocate-to-RAM boot ladder + wire
; client + keyboard-matrix console, minted by the same foundry and config
; block as the Altair template (ADR-0006). M3 tasks 4.1-4.6.
;
; Why this file looks nothing like machine/bios.asm's memory layout: on a
; Model 4 the system ROM and page-zero RAM are mutually exclusive (there is
; no shadow-ROM trick like the 4P's port 9Ch -- docs/research/
; trs80-model4-emulation.md). Reset lands at 0000h with port 84h's memory
; map at "00" (ROM 0000-37FF, keyboard 3800-3BFF, video 3C00-3FFF, RAM
; 4000-FFFF). This template copies itself into that already-present RAM
; above 4000h, jumps into the copy, and only then switches the map to "10"
; (RAM 0000-F3FF, keyboard F400-F7FF, video F800-FFFF) -- which is when
; page zero starts to exist. Proved in isolation first, per task 4.1, as
; build/probe/m4reloc.asm/reloc_test.py (throwaway, not part of this file).
;
; The relocation trick is zmac's phase/dephase: everything from `body:` on
; is stored at its low ROM load address (so it fits the 0000-37FF window)
; but labelled as though it already lived at RELOC. Copying byte-for-byte
; from address 0 to RELOC then lands every phase-section byte exactly on
; the address its own label says it is at -- verified against a throwaway
; scratch case (since discarded) before this file was written, and again
; end-to-end by the 4.1 proof above. No jump-table or fixup is needed.
;
; Console hardware is nothing like the Altair's: there is no second serial
; port for a human operator (docs/research/trs80-model4-emulation.md, task
; 1.1 -- "-ip" and "-rB" are both dead under a custom ROM). The console IS
; the video RAM + keyboard matrix, real on this machine and real over VNC
; on a person's trs80gp window; a keyboard-matrix driver reads it (task
; 4.6) and every character this ROM prints also goes out the printer tap
; (F8h), which is the byte channel the M3 harness actually asserts against
; (task 4.3). The wire (server protocol: HELLO etc.) is the TR1865 UART at
; E8h-EBh -- the machine's only other I/O-mapped serial device, and
; entirely separate from the console.
;
; 8080 instruction subset by default, matching bios.asm's rule so the two
; templates share a portable dialect even though only the Altair template
; has to run under "set cpu 8080" today. Every opcode in this file is
; verified 8080-subset; the CPU actually driving it is a Z80, so this is a
; stricter-than-required constraint kept for parity, not a hardware need.
;
; Immediate-operand OUT/IN only, never OUT (C),A: the M3 1.1 research
; recorded that opcode form as unreliable on trs80gp's I/O dispatch (it
; never reached the printer tap in the port-sweep probe), and it is Z80-only
; besides.

	.8080

	include 'machine/protocol.inc'
	include 'machine/config.inc'	; the pinned block-layout equates
					; (CFG_OFF_*/CFG_LEN_*, CFGBLKLEN,
					; CFGBLKRES, CFG_PLAT_*, CFG_ST_*) --
					; one source of truth shared with the
					; Altair template and pinned against
					; server/configblock.py by
					; server/tests/test_config_inc_pins.py.
					; config.inc's own CFGBLK equ (0E100h)
					; is Altair's absolute load address and
					; is NOT used here; this template's
					; block sits at a different address
					; (CFGBLK_RT below) because it's copied
					; into RAM at cold boot -- see CB_OFF.

; ---------------------------------------------------- hardware constants

RELOC	equ	4000h		; relocation target: RAM already present at
				; reset (map 00 has RAM from 4000h up)
MAPREG	equ	84h		; memory-map select, write-only, mirrored 84h-87h
MAPM4	equ	02h		; bits 1:0 = 10: Model 4 layout (RAM 0000-F3FF,
				; keyboard F400-F7FF, video F800-FFFF);
				; bits 6:2 = 0 selects 64x16, bank 0, no reverse

; TR1865 UART, the wire (server protocol) -- separate from the console.
; Fixed at E8h-EBh: the block's link config carries port_base/reset/mode/
; baud as *values*, but the port numbers themselves are this platform's
; only real UART address and are compiled in, the same way bios.asm's
; console ports are compiled in and only the framing bytes are burned-in
; data (design.md "Config block v1 layout").
WRSTP	equ	0E8h		; out: master reset (value from the block,
				; ignored by the hardware). in: modem status
WBAUDP	equ	0E9h		; out: baud rate (value from the block)
WCTLP	equ	0EAh		; out: control (value from the block).
				; in: UART status -- 80h RDA, 40h TXE
WDATAP	equ	0EBh		; in/out: data register
WRDA	equ	80h		; status: receive data available
WTXE	equ	40h		; status: transmitter empty
TOUTER	equ	4		; outer x 65536 inner polls per byte timeout.
				; Deliberately NOT bios.asm's 16: measured
				; empirically (build/probe/m4boot_test.py
				; against a minted image with nothing on the
				; wire) that 16 takes several minutes of real
				; wall clock on trs80gp's Z80 timing before
				; HELLO's bounded retry gives up, while 4
				; reaches the Local-Only prompt in ~5
				; seconds and 2 in ~4 -- the two platforms'
				; relationship between this constant and real
				; time is not the same, and 16 (tuned for
				; SIMH's Altair timing) is impractically slow
				; here. Real HELLO round-trips never approach
				; this bound either way; it only governs how
				; long a genuinely dead link takes to be
				; declared dead.

PRT	equ	0F8h		; printer port: OUT (F8h),A writes + strobes.
				; Pacing between characters is load-bearing --
				; see PDELAY below and the puts comment.
PDELAY	equ	400h		; per-character printer-tap delay. Measured
				; empirically in the 4.1 proof: back-to-back
				; OUT (F8h),A with no pacing loses ~2 of every
				; 3 bytes to the emulated printer's own
				; strobe timing (a fixed-stride loss, not the
				; TCP connect race -- that hazard is separate
				; and is why the boot report prints twice,
				; see BOOTREPS below). This value is the
				; smallest tested that produced zero loss
				; across a multi-second capture; it is not
				; the tightest possible bound.
BOOTREPS equ	2		; the boot-time auto-report (config + ls
				; /dev, task 4.6) prints this many times, so
				; a scenario built against a fresh printer-tap
				; connection still sees one clean, complete
				; copy even if the very first repetition
				; catches the tail end of the connect race.

; Keyboard matrix, map 10: F400h-F7FFh, address bit N of the low byte
; selects row N (same decode scheme as the Model I/III matrix at 3800h,
; rebased -- docs/research/trs80-model4-emulation.md).
KBBASE	equ	0F400h

VIDBASE	equ	0F800h		; video RAM window in map 10 (2 KB; we use the
				; low 1 KB for 64x16, matching MAPM4's mode bits)
VIDLEN	equ	400h		; 1024 chars, 64 cols x 16 rows

STACK	equ	0FE00h		; RAM in both maps (4000h-FFFFh is common to
				; map 00 and map 10 -- design.md)

; -------------------------------------------------------- config block
;
; Same v1 layout as the Altair template. Field offsets/lengths within the
; block (CFG_OFF_*/CFG_LEN_*, CFGBLKLEN, CFGBLKRES, CFG_PLAT_*, CFG_ST_*)
; come from the included machine/config.inc -- no second hand-copied set
; of numbers to drift out of sync with server/configblock.py. The one
; thing config.inc does NOT give this template is the block's *address*:
; its CFGBLK equ (0E100h) is the Altair template's absolute load address,
; which has no meaning here -- this template's block is copied into RAM
; at cold boot, so its offset from the template's own base is a genuinely
; different, M4-specific placement decision (task 4.4).
CB_OFF	equ	100h		; file offset of CFGBLK from the template's own
				; base -- the SAME offset as the Altair
				; template's block-from-org-0E000h (design.md,
				; task 4.4), even though the Altair template's
				; "base" is its relocated org and this
				; template's base is the ROM's own 0000h.

CFGBLK_RT equ	RELOC+CB_OFF	; the block's address once relocated (4100h)
				; -- this is where the BIOS actually reads
				; it from; the ROM-resident copy at CB_OFF
				; is never read after the map switch, since
				; the ROM itself is gone by then.

; -------------------------------------------------- retained drive map
;
; Exactly DMAP's shape on the Altair template (machine/bios.asm): fixed-
; stride entries, so preloading from the block's cached map is a bulk copy,
; not a parse (design.md).
DMAPN	equ	16
DNAMEL	equ	16
DENTSZ	equ	20

; ------------------------------------------------------ vector page

	org	0
	jmp	init0		; 0000: reset vector. Real ROM address; this
				; is the ONLY code in this file that has to
				; run correctly from ROM before relocation.

	org	CB_OFF
CFGBLKM4: ds	CFGBLKRES	; named CFGBLKM4, not CFGBLK: config.inc
				; already defines CFGBLK as the Altair
				; template's absolute address (0E100h), an
				; equ, not a label -- reusing the name here
				; for a label at a different address would
				; collide. The foundry stamps this region at
				; mint time; an unminted template leaves it
				; all zero, which fails the magic check
				; honestly.

	org	CB_OFF+CFGBLKRES	; = 0300h; explicit for clarity, though
					; the reservation above already lands here

; -------------------------------------------------- pre-relocation init
;
; Runs directly from ROM (map 00, still active). Nothing here may assume
; page zero exists -- it doesn't yet.
init0:	di
	lxi	sp,STACK	; RAM at 4000h+ already exists at map 00
	lxi	h,0
	lxi	d,RELOC
	lxi	b,IMGLEN
	call	cpblk		; copy this whole image (vectors, block,
	jmp	body		; and the phase-relabelled body) into RAM
				; body's assembled value is already RELOC-
				; relative -- see the file header

; Copy BC bytes from HL to DE.
cpblk:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcx	b
	mov	a,b
	ora	c
	jnz	cpblk
	ret

bodyload equ	$
	phase	RELOC+bodyload

; --------------------------------------------------- relocated body
;
; Everything from here to `dephase` executes from the RAM copy. Labels are
; already RELOC-relative (see the file header); the bytes backing them live
; at their ROM load address (bodyload+) and get carried to RELOC+bodyload+
; by the init0 copy above, landing exactly where their own label says.

body:	mvi	a,MAPM4
	out	MAPREG		; page zero is ROM/keyboard/video no longer

	call	setp0		; lay down the CP/M vectors before anything
				; below touches page zero (task 4.2)
	call	vclr		; blank the screen; best-effort, not tested
	xra	a
	sta	LINKUP
	sta	MAPCNT
	sta	CBVFLG
	mvi	a,0FFh
	sta	DEFDRV

	lxi	h,mbann		; banner: first visible act after the map
	call	puts		; switch, from the relocated copy (the
				; scenario this proves)

	mvi	a,1		; this ROM only ever runs on a Z80 (there is
	sta	INVCPU		; no 8080 variant of this hardware); reported
	mvi	a,61		; rather than probed, unlike the Altair
	sta	INVRAM		; template's variable-population ramsz --
				; RAM in map 10 is a fixed 0000-F3FF, and
				; 0F400h / 1024 = 61 exactly

	call	cbvalid
	jc	cbbad
	mvi	a,1
	sta	CBVFLG
	call	applyblk	; machine id, TR1865 bring-up, DMAP preload --
				; all before the wire is touched (D6)
	call	hello
	jnc	helok
	lxi	h,mnosrv
	call	puts
	jmp	bootrep

helok:	mvi	a,1
	sta	LINKUP
	lda	DEFDRV
	inr	a		; 0FFh -> 0: linked, but nothing bound
	jz	hbare
	lxi	h,mlink
	call	puts
	lda	DEFDRV
	adi	'A'
	call	putc
	lxi	h,mlink2
	call	puts
	jmp	bootrep
hbare:	lxi	h,mlink0
	call	puts
	jmp	bootrep

cbbad:	lxi	h,mcbbad
	call	puts
	; falls through: LINKUP/MAPCNT/DEFDRV already zeroed/cleared above,
	; and hello is never attempted -- an unminted template boots
	; honestly with no baked bindings at all (nothing to preload)

; Boot-time auto-report (task 4.6): the config-block report and `ls /dev`,
; unprompted, right after the banner and HELLO attempt -- neither touches
; the wire, so this is safe in every link state. Printed BOOTREPS times:
; the printer tap's own connect race can still drop bytes from the very
; first repetition even with per-character pacing (that pacing fixes the
; emulated printer's strobe-timing loss, a *different* hazard -- see
; PDELAY above), so a scenario asserting on this output should look for
; the LAST repetition, guaranteed complete once the tap connection has
; had time to settle.
bootrep:
	mvi	b,BOOTREPS
bootrp1:
	push	b
	call	cfgcmd
	call	lsdev
	pop	b
	dcr	b
	jnz	bootrp1

	call	bootdemo	; task-order fix: dir/type/run, headlessly
				; proven (skips itself in Local-Only mode)
	jmp	prompt

; Auto-demo, link-up only: proves dir/type/run actually work over the wire
; without any scripted keystrokes (there is no scriptable input channel --
; docs/research/trs80-model4-emulation.md, task 1.1). Feeds synthetic
; command lines through the *real* interactive path -- kwcmp for dispatch,
; fnparse for the filename -- rather than poking FNAME directly, so this
; exercises the same code an operator's typing would. Runs once (not
; BOOTREPS times: unlike the static config/ls text, DIR/FREAD responses
; are themselves proof the link is alive, and doubling would duplicate a
; DIR listing and a COM run in the transcript for no benefit). Each step
; gets its own "boot demo: ..." prefix line so a human at the prompt
; understands why output appeared unprompted, and so a harness oracle has
; an anchor to key off before each command's own output.
bootdemo:
	lda	LINKUP
	ora	a
	rz			; local-only: nothing to demo, skip entirely

	lxi	h,mdemodir
	call	puts
	lxi	h,DEMODIR
	shld	CMDP
	call	dircmd
	call	crlf

	lxi	h,mdemotyp
	call	puts
	lxi	h,DEMOTYP
	shld	CMDP
	lxi	d,kwtype
	call	kwcmp		; carry clear, HL at the delimiter (same
	call	fnparse		; contract the real prompt dispatch relies on)
	call	typecmd
	call	crlf

	lxi	h,mdemorun
	call	puts
	lxi	h,DEMORUN
	shld	CMDP
	lxi	d,kwrun
	call	kwcmp
	call	fnparse
	call	runcmd		; on success this does not return here -- it
	ret			; jumps into the TPA; only reached on failure

; --------------------------------------------------- config block

; Validate CFGBLK_RT: magic 'RNXC', version, platform id, checksum -- all
; against the pinned constants from machine/config.inc, never a hand-copied
; second set of numbers. Carry set = bad.
cbvalid:
	lxi	h,CFGBLK_RT+CFG_OFF_MAGIC
	mov	a,m
	cpi	'R'
	jnz	cbbad1
	inx	h
	mov	a,m
	cpi	'N'
	jnz	cbbad1
	inx	h
	mov	a,m
	cpi	'X'
	jnz	cbbad1
	inx	h
	mov	a,m
	cpi	'C'
	jnz	cbbad1
	lda	CFGBLK_RT+CFG_OFF_VERSION
	cpi	CFG_VERSION
	jnz	cbbad1
	lda	CFGBLK_RT+CFG_OFF_PLATFORM	; a block stamped for the wrong
	cpi	CFG_PLAT_MODEL4			; platform (e.g. Altair) must
	jnz	cbbad1				; fail here, not pass silently
	lxi	h,CFGBLK_RT
	lxi	b,CFGBLKLEN
	mvi	d,0		; running checksum
cbvlp:	mov	a,m
	add	d
	mov	d,a
	inx	h
	dcx	b
	mov	a,b
	ora	c
	jnz	cbvlp
	mov	a,d
	ora	a
	jnz	cbbad1
	xra	a		; carry already clear
	ret
cbbad1:	stc
	ret

; Apply a validated block: machine id into HELLOP, TR1865 bring-up from the
; link bytes, and the cached drive map into DMAP -- all before hello() is
; ever called (D6, "The baked drive map pre-populates the retained map").
applyblk:
	lxi	h,CFGBLK_RT+CFG_OFF_MACHID
	lxi	d,HELLOP
	mvi	c,4
ablp1:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcr	c
	jnz	ablp1

	lxi	h,CFGBLK_RT+CFG_OFF_LINK
	mov	a,m		; port_base -- kept for `config` display only;
	sta	WPORTB		; the real ports are the WRSTP/WBAUDP/WCTLP/
	inx	h		; WDATAP equates above (immediate-operand OUT
	mov	a,m		; needs a compile-time port, not a runtime one)
	sta	WLRESET
	inx	h
	mov	a,m
	sta	WLMODE
	inx	h
	mov	a,m
	sta	WLBAUD

	; TR1865 init, in the order the M3 research verified: master reset,
	; then baud, then control (docs/research/trs80-model4-emulation.md)
	lda	WLRESET
	out	WRSTP
	lda	WLBAUD
	out	WBAUDP
	lda	WLMODE
	out	WCTLP
	mvi	a,1
	sta	INVSER

	; cached drive map: exactly DMAP's shape, so this is a bulk copy,
	; not a parse (design.md "Config block v1 layout")
	lda	CFGBLK_RT+CFG_OFF_MAPCNT
	cpi	DMAPN+1
	jc	abmc1
	mvi	a,DMAPN
abmc1:	sta	MAPCNT
	mov	b,a		; B = clamped entry count
	lxi	h,0		; HL accumulates count * DENTSZ
	lxi	d,DENTSZ
abmul:	mov	a,b
	ora	a
	jz	abmuld
	dad	d
	dcr	b
	jmp	abmul
abmuld:	mov	b,h
	mov	c,l		; BC = bytes to copy
	mov	a,b
	ora	c
	jz	abmno
	lxi	h,CFGBLK_RT+CFG_OFF_MAP
	lxi	d,DMAP
abmcp:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcx	b
	mov	a,b
	ora	c
	jnz	abmcp
	lda	DMAP		; default drive = the first preloaded entry
	sta	DEFDRV
	ret
abmno:	mvi	a,0FFh
	sta	DEFDRV
	ret

; --------------------------------------------------- page zero (4.2)

; Lay down the CP/M vectors. The "JMP 0" and "JMP bdoshim" targets both
; live in the relocated body (RAM at 4000h+, common to both memory maps --
; design.md), never inside 0000-3FFFh: a soft-reset vector that tried to
; switch the map back to 00 *from inside page zero itself* would have the
; rest of its own bytes silently replaced out from under it the instant
; the OUT took effect, since 0000-37FFh is exactly the range that changes
; meaning across the switch. Landing the trampoline in the always-RAM
; region sidesteps that entirely.
setp0:	lxi	h,P0IMG
	lxi	d,0
	mvi	b,P0LEN
setp0l:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcr	b
	jnz	setp0l
	ret

; JMP 0 lands here (from a loaded program, or bdoshim's warm-boot request):
; switch back to map 00 (ROM back in) and re-enter the real reset vector.
softrst:
	di
	xra	a
	out	MAPREG
	jmp	0

; --------------------------------------------------------- console io
;
; putc mirrors every character to the video RAM (best-effort, for a human
; at the trs80gp window or on real iron -- not the tested channel) and to
; the printer tap (the tested channel; task 4.3). getc reads the keyboard
; matrix (task 4.6).

putc:	push	psw
	call	vputc
	pop	psw
	push	psw
	out	PRT
	push	b
	lxi	b,PDELAY	; pacing is load-bearing here -- see PDELAY
pcdly:	dcx	b		; above and the 4.1 proof (build/probe/
	mov	a,b		; m4reloc.asm) that measured it
	ora	c
	jnz	pcdly
	pop	b
	pop	psw
	ret

; Best-effort video echo, 64x16 (matches MAPM4's mode bits). No scrolling:
; the cursor wraps to the top of the window at the bottom. CR alone
; advances to the next row (every crlf below pairs CR with a following LF,
; which is swallowed as a no-op); there is no bare "return without
; newline" mode.
vputc:	push	h
	push	d
	push	psw
	cpi	0Dh
	jz	vcr
	cpi	0Ah
	jz	vdone
	lhld	VCUR
	lxi	d,VIDBASE
	dad	d
	pop	psw
	push	psw
	mov	m,a
	lhld	VCUR
	inx	h
	mov	a,h
	ani	3		; wrap at 1024 (10-bit range)
	mov	h,a
	shld	VCUR
	jmp	vdone
vcr:	lhld	VCUR
	mov	a,l
	ori	3Fh		; round up to the next 64-byte row boundary
	mov	l,a
	inx	h
	mov	a,h
	ani	3
	mov	h,a
	shld	VCUR
vdone:	pop	psw
	pop	d
	pop	h
	ret

; Blank the video window and home the cursor.
vclr:	lxi	h,VIDBASE
	lxi	b,VIDLEN
vclrlp:	mvi	m,' '
	inx	h
	dcx	b
	mov	a,b
	ora	c
	jnz	vclrlp
	xra	a
	sta	VCUR
	sta	VCUR+1
	ret

puts:	mov	a,m
	ora	a
	rz
	call	putc
	inx	h
	jmp	puts

crlf:	mvi	a,0Dh
	call	putc
	mvi	a,0Ah
	jmp	putc

; Blocking keyboard read -> A. Scans all 8 matrix rows; row 7 (shift/ctrl/
; caps/F-keys) never decodes to a character on its own -- shifted symbols
; are not implemented (documented scope cut, see the report: this is an
; interactive-convenience driver with no scriptable way to verify it).
; Edge-triggered: once a mapped key decodes, the routine waits for that
; row to read zero again before returning, so a held key does not
; repeat-fire.
getc:
getc0:	mvi	d,0		; row counter, 0-7
	mvi	e,1		; row bitmask = 1 << row
getcrw:	mov	a,d
	cpi	8
	jz	getc0
	mvi	h,0F4h
	mov	l,e
	mov	a,m
	ora	a
	jz	getcnx
	call	bitidx		; C = bit index within the row
	mov	b,c
	mov	a,d
	rlc
	rlc
	rlc			; a = row * 8
	add	b
	mvi	h,0
	mov	l,a
	lxi	d,KBTAB
	dad	d
	mov	a,m
	ora	a
	jz	getcnx		; unmapped position (modifier or blank)
	sta	KBCHR
getcwt:	mvi	h,0F4h		; wait for release before returning
	mov	l,e
	mov	a,m
	ora	a
	jnz	getcwt
	lda	KBCHR
	ret
getcnx:	inr	d
	mov	a,e
	add	a
	mov	e,a
	jmp	getcrw

; A = a nonzero byte; returns C = index of its lowest set bit (0-7).
; Clobbers A.
bitidx:	mvi	c,0
bilp:	rrc
	jc	bidone
	inr	c
	jmp	bilp
bidone:	ret

; ------------------------------------------------------- wire bytes
;
; Same algorithm as machine/bios.asm's wtx/wrx, against the TR1865's
; status bits instead of the M2SIO ACIA's. No carrier/DCD gating: the M3
; research established the TCP connect race (dropped first byte) as this
; platform's hazard but did not establish an M2SIO-style "TDRE-ready-with-
; nobody-there" failure mode for the TR1865, so the defense here is the
; same bounded retry design.md names for this platform -- rpc()'s
; RETRIES loop (protocol.inc), unchanged from the Altair template.

; Send A over the wire; carry set on timeout.
wtx:	mov	b,a
	mvi	a,TOUTER
	sta	TOUT
wtxo:	lxi	d,0
wtx1:	in	WCTLP
	ani	WTXE
	jnz	wtx2
	dcx	d
	mov	a,d
	ora	e
	jnz	wtx1
	lda	TOUT
	dcr	a
	sta	TOUT
	jnz	wtxo
	stc
	ret
wtx2:	mov	a,b
	out	WDATAP
	ora	a
	ret

; Receive a byte -> A; carry set on timeout.
wrx:	mvi	a,TOUTER
	sta	TOUT
wrxo:	lxi	d,0
wrx1:	in	WCTLP
	ani	WRDA
	jnz	wrx2
	dcx	d
	mov	a,d
	ora	e
	jnz	wrx1
	lda	TOUT
	dcr	a
	sta	TOUT
	jnz	wrxo
	stc
	ret
wrx2:	in	WDATAP
	ora	a
	ret

; Add A into the running checksum, then transmit it.
sadd:	push	b
	mov	b,a
	lda	CKSUM
	add	b
	sta	CKSUM
	mov	a,b
	pop	b
	jmp	wtx

; Receive a byte, add it into the running checksum -> A.
wrxs:	call	wrx
	rc
	push	b
	mov	b,a
	lda	CKSUM
	add	b
	sta	CKSUM
	mov	a,b
	pop	b
	ora	a
	ret

; ------------------------------------------------------ wire frames
;
; Byte-for-byte the same framing as machine/bios.asm (machine/protocol.inc
; is shared, read-only, unmodified).

sndfrm:	xra	a
	sta	CKSUM
	mvi	a,PVER
	call	sadd
	rc
	lda	FUNC
	call	sadd
	rc
	mov	a,c
	call	sadd
	rc
	xra	a
	call	sadd
	rc
	mov	a,c
	ora	a
	jz	sndck
sndlp:	mov	a,m
	call	sadd
	rc
	inx	h
	dcr	c
	jnz	sndlp
sndck:	lda	CKSUM
	cma
	inr	a
	jmp	wtx

rcvfrm:	xra	a
	sta	CKSUM
	sta	RIDX
	lhld	RDST
	shld	RPTR
	call	wrxs
	rc
	cpi	PVER
	jnz	rcvbad
	call	wrxs
	rc
	sta	RFN
	call	wrxs
	rc
	sta	RCNT
	call	wrxs
	rc
	sta	RCNT+1
rcvlp:	lda	RCNT
	mov	l,a
	lda	RCNT+1
	mov	h,a
	ora	l
	jz	rcvck
	dcx	h
	mov	a,l
	sta	RCNT
	mov	a,h
	sta	RCNT+1
	call	wrxs
	rc
	mov	b,a
	lda	RIDX
	cpi	3
	jnc	rcvhi
	mov	e,a
	mvi	d,0
	lxi	h,RBUF
	dad	d
	mov	m,b
	lda	RIDX
	inr	a
	sta	RIDX
	jmp	rcvlp
rcvhi:	lhld	RPTR
	mov	m,b
	inx	h
	shld	RPTR
	jmp	rcvlp
rcvck:	call	wrxs
	rc
	lda	CKSUM
	ora	a
	jnz	rcvbad
	ret
rcvbad:	stc
	ret

; Request/response with bounded retry (ADR-0003, unchanged): this is the
; mechanism that survives this platform's dropped first byte (task 4.5) --
; the first attempt's frame is lost or garbled by the connect race, its
; checksum or timeout fails, and the retry lands on an already-open
; connection.
rpc:	mvi	a,RETRIES
	sta	TRIES
rpc1:	lhld	PPTR
	lda	PLEN
	mov	c,a
	call	sndfrm
	jc	rpc2
	call	rcvfrm
	jc	rpc2
	lda	FUNC
	ori	FRESP
	mov	b,a
	lda	RFN
	cmp	b
	jz	rpcok
rpc2:	lda	TRIES
	dcr	a
	sta	TRIES
	jnz	rpc1
	xra	a
	sta	LINKUP
	stc
	ret
rpcok:	xra	a
	ret

; ------------------------------------------------------------ hello

hello:	lda	INVCPU
	sta	HELLOP+7
	lda	INVRAM
	sta	HELLOP+8
	lda	INVSER
	sta	HELLOP+9
	mvi	a,FHELLO
	sta	FUNC
	lxi	h,HELLOP
	shld	PPTR
	mvi	a,10
	sta	PLEN
	lxi	h,RBUF+3
	shld	RDST
	call	rpc
	jnc	hresp
	mvi	a,0FFh
	sta	HERR
	stc
	ret
hresp:	lda	RBUF
	sta	HERR
	ora	a
	jz	hok
	stc
	ret

; Parse the whole response into the retained map -- identical logic to
; machine/bios.asm's hok, just against this file's own DMAP/RBUF.
hok:	mvi	a,0FFh
	sta	DEFDRV
	lda	RBUF+1
	cpi	DMAPN+1
	jc	hok1
	mvi	a,DMAPN
hok1:	sta	MAPCNT
	ora	a
	rz
	sta	MWALK
	lxi	h,RBUF+2
	shld	SPTR
	lxi	h,DMAP
	shld	DPTR
hoke:	lhld	SPTR
	mov	a,m
	sta	PDRV
	inx	h
	inx	h
	inx	h
	mov	a,m
	sta	NLEN
	lda	DEFDRV
	inr	a
	jnz	hokc
	lda	PDRV
	sta	DEFDRV
hokc:	lhld	DPTR
	xchg
	lhld	SPTR
	mvi	c,3
hokh:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcr	c
	jnz	hokh
	inx	h
	lda	NLEN
	cpi	DNAMEL+1
	jc	hokn
	mvi	a,DNAMEL
hokn:	stax	d
	inx	d
	ora	a
	jz	hokp
	mov	c,a
hokl:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcr	c
	jnz	hokl
hokp:	lhld	SPTR
	lxi	d,4
	dad	d
	lda	NLEN
	mov	e,a
	mvi	d,0
	dad	d
	shld	SPTR
	call	dnext
	jnz	hoke
	xra	a
	ret

; -------------------------------------------------- dir / type / run
;
; Byte-for-byte the same algorithms as machine/bios.asm's dircmd/setfrq/
; frdchk/frqadv/frfull/typecmd/runcmd -- only the console driver (putc,
; already paced for this platform) and the TPA placement differ. The base
; machine-boot spec requires these unqualified; design.md's "narrow to
; boot + HELLO + config" escape hatch only applied if the image didn't fit
; under 37FF, and it does (well under half the window even with these
; added).
;
; TPA lives at 0100h, below the relocated body at RELOC (4000h): once the
; map switch lands (task 4.1), 0100h-3FFFh is ordinary RAM that nothing
; else in this template uses -- unlike the Altair template, which needs no
; separate TPA-below-the-monitor placement because its monitor lives high
; (0E000h) already. TPATOP is RELOC itself: a loaded program must never
; reach the resident code it would need to keep running.
TPA	equ	0100h
TPATOP	equ	RELOC		; = 4000h; must not touch the relocated body

; /dev is synthetic; DIR is not (ADR-0004) -- lists the volume bound to
; DEFDRV over the wire, same FDIR verb the Altair template uses.
dircmd:	lda	LINKUP
	ora	a
	jnz	dirgo
	lxi	h,mnolnk
	jmp	puts
dirgo:	lda	DEFDRV
	sta	DIRP
	mvi	a,FDIR
	sta	FUNC
	lxi	h,DIRP
	shld	PPTR
	mvi	a,1
	sta	PLEN
	lxi	h,RBUF+3
	shld	RDST
	call	rpc
	jnc	dir1
	lxi	h,mwerr
	jmp	puts
dir1:	lda	RBUF
	ora	a
	jz	dir2
	jmp	cserr
dir2:	lda	RBUF+1		; entry count (low byte; fits M1 volumes)
	sta	DCNT
	lxi	h,RBUF+3
	shld	ENTP
dirlp:	lda	DCNT
	ora	a
	rz
	lhld	ENTP		; name, 8 chars
	mvi	c,8
	call	putfn
	mvi	a,'.'
	call	putc
	lhld	ENTP		; extension, 3 chars
	lxi	d,8
	dad	d
	mvi	c,3
	call	putfn
	mvi	a,' '
	call	putc
	lhld	ENTP		; size, 32-bit little-endian
	lxi	d,11
	dad	d
	mov	e,m
	inx	h
	mov	d,m
	inx	h
	mov	a,m
	inx	h
	ora	m
	jz	dirsz
	lxi	h,mbig		; >64K: don't lie with a truncated number
	call	puts
	jmp	dirnx
dirsz:	xchg
	call	pdec16
dirnx:	call	crlf
	lhld	ENTP
	lxi	d,15
	dad	d
	shld	ENTP
	lda	DCNT
	dcr	a
	sta	DCNT
	jmp	dirlp

; Fill the FREAD request from FNAME/DEFDRV; offset 0, chunk length 512.
setfrq:	lda	DEFDRV
	sta	FRQ
	lxi	h,FNAME
	lxi	d,FRQ+1
	mvi	c,11
sfq1:	mov	a,m
	stax	d
	inx	h
	inx	d
	dcr	c
	jnz	sfq1
	xra	a
	sta	FRQ+12		; offset = 0
	sta	FRQ+13
	sta	FRQ+14
	sta	FRQ+15
	sta	FRQ+16		; length = 512
	mvi	a,2
	sta	FRQ+17
	ret

; One FREAD chunk: request in FRQ, payload data lands at [RDST].
; Carry = wire failure; else RBUF holds result + actual count.
frdchk:	mvi	a,FREAD
	sta	FUNC
	lxi	h,FRQ
	shld	PPTR
	mvi	a,18
	sta	PLEN
	jmp	rpc

; Advance the request offset by one chunk (512).
frqadv:	lda	FRQ+13
	adi	2
	sta	FRQ+13
	rnc
	lda	FRQ+14
	inr	a
	sta	FRQ+14
	ret

; Did the last chunk come back full (actual == 512)?  Z flag = yes.
frfull:	lda	RBUF+2
	cpi	2
	rnz
	lda	RBUF+1
	ora	a
	ret

typecmd:
	lda	LINKUP
	ora	a
	jnz	typ0
	lxi	h,mnolnk
	jmp	puts
typ0:	call	setfrq
typlp:	lxi	h,TYPBUF
	shld	RDST
	call	frdchk
	jc	cwerr
	lda	RBUF
	cpi	RFNF
	jz	cnotf
	ora	a
	jnz	cserr
	lda	RBUF+1		; DE = actual count
	mov	e,a
	lda	RBUF+2
	mov	d,a
	lxi	h,TYPBUF
typ1:	mov	a,d
	ora	e
	jz	typ2
	mov	a,m
	cpi	1Ah		; ^Z: CP/M text EOF
	rz
	call	putc
	inx	h
	dcx	d
	jmp	typ1
typ2:	call	frfull
	rnz			; short chunk: done
	call	frqadv
	jmp	typlp

runcmd:	lda	LINKUP
	ora	a
	jnz	run0
	lxi	h,mnolnk
	jmp	puts
run0:	call	setfrq
	lxi	h,TPA
	shld	RDST
runlp:	lda	RDST+1		; dest + 512 must stay under TPATOP
	cpi	(TPATOP/256)-2
	jnc	ctoobig
	call	frdchk
	jc	cwerr
	lda	RBUF
	cpi	RFNF
	jz	cnotf
	ora	a
	jnz	cserr
	call	frfull
	jnz	runfin
	lhld	RPTR		; next chunk continues where this ended
	shld	RDST
	call	frqadv
	jmp	runlp
runfin:	lhld	RPTR		; empty file: nothing to jump to
	mov	a,h
	cpi	TPA/256
	jnz	rungo
	mov	a,l
	ora	a
	jnz	rungo
	lxi	h,mempty
	jmp	puts
rungo:	lxi	h,warmret	; RET from the program lands at the prompt
	push	h
	jmp	TPA		; real bits, real CPU

; ------------------------------------------------------------ bind
;
; Re-runs the HELLO rung on demand. No carrier-latch handling (unlike
; machine/bios.asm's bindcmd): that logic exists there for the M2SIO
; ACIA's specific "carrier loss latches until the data register is read"
; quirk, which the research did not establish for the TR1865. A bounded
; drain, then a fresh hello, is what's implemented here.
bindcmd:
	call	wdrain
	xra	a
	sta	LINKUP
	call	hello
	jc	bindno
	mvi	a,1
	sta	LINKUP
	lxi	h,mbindok
	call	puts
	jmp	pmap
bindno:	lda	HERR
	cpi	0FFh
	jz	bindnr
	cpi	RUNKMCH
	jz	bindunk
	lxi	h,mbrefu
	call	puts
	lda	HERR
	call	phexp
	call	crlf
	jmp	blocal
bindunk:
	lxi	h,mbunk
	call	puts
	jmp	blocal
bindnr:	lxi	h,mbnores
	call	puts
blocal:	lxi	h,mnosrv
	jmp	puts

; Swallow whatever the UART is still holding, bounded so a chattering peer
; can't trap us here.
wdrain:	lxi	d,512
wdr1:	in	WCTLP
	ani	WRDA
	rz
	in	WDATAP
	dcx	d
	mov	a,d
	ora	e
	jnz	wdr1
	ret

; ------------------------------------------------- drive map report
;
; Identical logic to machine/bios.asm's equivalents, against this file's
; own DMAP.

dnext:	lhld	DPTR
	lxi	d,DENTSZ
	dad	d
	shld	DPTR
	lda	MWALK
	dcr	a
	sta	MWALK
	ret

dfind:	sta	DFDRV
	lda	MAPCNT
	ora	a
	jz	dfno
	mov	c,a
	lxi	h,DMAP
dfl:	mov	a,m
	mov	b,a
	lda	DFDRV
	cmp	b
	jz	dfyes
	lxi	d,DENTSZ
	dad	d
	dcr	c
	jnz	dfl
dfno:	stc
	ret
dfyes:	xra	a
	ret

pdent:	push	h
	inx	h
	inx	h
	inx	h
	mov	c,m
	inx	h
	mov	a,c
	ora	a
	jz	pdent2
pdent1:	mov	a,m
	call	putc
	inx	h
	dcr	c
	jnz	pdent1
pdent2:	lda	LINKUP
	ora	a
	jnz	pdent3
	lxi	h,mdead
	call	puts
pdent3:	pop	h
	ret

pdlet:	push	psw
	lxi	h,mind
	call	puts
	pop	psw
	adi	'a'
	call	putc
	mvi	a,':'
	call	putc
	mvi	a,' '
	jmp	putc

pdrvs:	xra	a
	sta	DIDX
pdrv1:	lda	DIDX
	call	pdlet
	lda	DIDX
	call	dfind
	jc	pdrvu
	call	pdent
	jmp	pdrvn
pdrvu:	lxi	h,munbnd
	call	puts
pdrvn:	call	crlf
	lda	DIDX
	inr	a
	sta	DIDX
	cpi	DMAPN
	jc	pdrv1
	ret

pmap:	lda	MAPCNT
	ora	a
	jz	pmapz
	sta	MWALK
	lxi	h,DMAP
	shld	DPTR
pmap1:	lhld	DPTR
	mov	a,m
	call	pdlet
	lhld	DPTR
	call	pdent
	call	crlf
	call	dnext
	jnz	pmap1
	ret
pmapz:	lxi	h,mnobnd
	jmp	puts

; ------------------------------------------------------------ ls
;
; /dev is synthetic and read-only (ADR-0004), same convention as the
; Altair template.

lscmd:	lxi	d,kwdev
	call	kwcmp
	jnc	lsdev
	lxi	h,mlsdev
	jmp	puts

lsdev:	lxi	h,mdev
	call	puts
	lxi	h,mdcpu
	call	puts
	lxi	h,mz80
	call	puts
	call	crlf
	lxi	h,mdram
	call	puts
	lda	INVRAM
	mov	l,a
	mvi	h,0
	call	pdec16
	lxi	h,mkb
	call	puts
	call	crlf
	lxi	h,mdcon		; the console is video + keyboard, not a
	call	puts		; serial port -- report the addresses it's
	call	crlf		; memory-mapped at instead of I/O ports
	lxi	h,mdwire
	call	puts
	mvi	a,WRSTP
	call	phexp
	mvi	a,'-'
	call	putc
	mvi	a,WDATAP
	call	phexp
	lxi	h,mdlink
	call	puts
	lda	LINKUP
	ora	a
	lxi	h,mdown
	jz	lsd2
	lxi	h,mup
lsd2:	call	puts
	call	crlf
	jmp	pdrvs

; ----------------------------------------------------------- config
;
; Reachable from every rung, never touches the wire, read-only -- same
; contract as the Altair template's cfgcmd, plus the config-block report
; (block validity, format version, stamped values) that ADDED Requirement
; "The config block is read and validated at cold boot" calls for.

cfgcmd:	lxi	h,mcfgb
	call	puts
	lda	CBVFLG
	ora	a
	lxi	h,mcbno
	jz	cfg0
	lxi	h,mcbok
cfg0:	call	puts
	call	crlf
	lxi	h,mcfgid
	call	puts
	call	pmid
	call	crlf
	lxi	h,mcfgrom
	call	puts
	call	prom
	call	crlf
	lxi	h,mcfgl1
	call	puts
	lda	WPORTB
	call	phexp
	lxi	h,mcfgl2
	call	puts
	lda	WLRESET
	call	phexp
	lxi	h,mcfgl3
	call	puts
	lda	WLMODE
	call	phexp
	lxi	h,mcfgl4
	call	puts
	lda	WLBAUD
	call	phexp
	call	crlf
	lxi	h,mcfgst
	call	puts
	lda	LINKUP
	ora	a
	lxi	h,mlocal
	jz	cfg1
	lxi	h,mup
cfg1:	call	puts
	call	crlf
	lxi	h,mcfgmap
	call	puts
	jmp	pmap

; Burned-in machine ID, 32-bit little-endian. Decimal while it fits 16
; bits, hex beyond that.
pmid:	lda	HELLOP+2
	mov	b,a
	lda	HELLOP+3
	ora	b
	jnz	pmidhx
	lda	HELLOP+1
	mov	h,a
	lda	HELLOP
	mov	l,a
	jmp	pdec16
pmidhx:	lda	HELLOP+3
	call	phex8
	lda	HELLOP+2
	call	phex8
	lda	HELLOP+1
	call	phex8
	lda	HELLOP
	call	phex8
	mvi	a,'h'
	jmp	putc

; Burned-in ROM version, major.minor.patch.
prom:	lda	HELLOP+4
	call	pdec8
	mvi	a,'.'
	call	putc
	lda	HELLOP+5
	call	pdec8
	mvi	a,'.'
	call	putc
	lda	HELLOP+6
pdec8:	mov	l,a
	mvi	h,0
	jmp	pdec16

; ------------------------------------------------------------- bdos
;
; Minimal console-only BDOS shim, same convention as machine/bios.asm:
; 0=warm boot, 1=conin+echo, 2=conout, 9=print $-string, 11=console
; status. fn0 (warm boot) goes to softrst, a full hardware reset -- the
; same behaviour as the Altair template's own `JMP 0` -> `cold`, since
; neither template keeps a separate reloadable CCP to warm-boot back into.
; runcmd (below) uses this as the BDOS a loaded COM file calls into.
bdoshim:
	mov	a,c
	ora	a
	jz	softrst
	cpi	1
	jz	bd1
	cpi	2
	jz	bd2
	cpi	9
	jz	bd9
	cpi	11
	jz	bd11
	mvi	a,0FFh
	mov	l,a
	ret
bd1:	call	getc
	call	putc
	mov	l,a
	ret
bd2:	mov	a,e
	jmp	putc
bd9:	ldax	d
	cpi	'$'
	rz
	call	putc
	inx	d
	jmp	bd9
bd11:	mvi	a,0FFh		; the keyboard matrix has no "any key waiting"
	mov	l,a		; status short of a full scan; honest 0FFh
	ret			; (never claims "not ready" falsely)

; RET from a loaded TPA program lands here (rungo below pushes this as the
; return address before jumping into TPA): the program's own stack is
; gone, so the monitor's is reasserted before anything else runs.
warmret:
	lxi	sp,STACK
	call	crlf
	jmp	prompt

; ---------------------------------------------------- error prints
;
; Shared by dir/type/run, same convention and messages as machine/bios.asm.
cnotf:	lxi	h,mnotf
	jmp	puts
cwerr:	lxi	h,mwerr
	jmp	puts
cserr:	lxi	h,mserr
	call	puts
	lda	RBUF
	adi	'0'
	call	putc
	jmp	crlf
ctoobig:
	lxi	h,mtoobg
	jmp	puts

; ------------------------------------------------------- utilities

; Print HL as unsigned decimal, leading zeros suppressed.
pdec16:	mvi	b,1
	lxi	d,-10000
	call	pdig
	lxi	d,-1000
	call	pdig
	lxi	d,-100
	call	pdig
	lxi	d,-10
	call	pdig
	mov	a,l
	adi	'0'
	jmp	putc
pdig:	mvi	c,'0'
pdglp:	dad	d
	jnc	pdgend
	inr	c
	jmp	pdglp
pdgend:	mov	a,e
	cma
	mov	e,a
	mov	a,d
	cma
	mov	d,a
	inx	d
	dad	d
	mov	a,c
	cpi	'0'
	jnz	pdgpr
	mov	a,b
	ora	a
	rnz
	mov	a,c
	jmp	putc
pdgpr:	mvi	b,0
	mov	a,c
	jmp	putc

; Print A as a two-digit hex byte with a trailing 'h'.
phexp:	call	phex8
	mvi	a,'h'
	jmp	putc

phex8:	push	psw
	rrc
	rrc
	rrc
	rrc
	call	phexd
	pop	psw
phexd:	ani	0Fh
	adi	'0'
	cpi	'9'+1
	jc	putc
	adi	7
	jmp	putc

skipsp:	mov	a,m
	cpi	' '
	rnz
	inx	h
	jmp	skipsp

; Print C bytes from HL, skipping pad spaces.
putfn:	mov	a,m
	cpi	' '
	jz	pfn1
	call	putc
pfn1:	inx	h
	dcr	c
	jnz	putfn
	ret

; Parse an 8.3 filename from [HL] into FNAME (space-padded, upcased).
; Carry set when no argument present.
fnparse:
	push	h
	lxi	h,FNAME
	mvi	c,11
fnp0:	mvi	m,' '
	inx	h
	dcr	c
	jnz	fnp0
	pop	h
fnps:	mov	a,m		; skip spaces before the argument
	cpi	' '
	jnz	fnp1
	inx	h
	jmp	fnps
fnp1:	ora	a
	jz	fnpbad
	lxi	d,FNAME		; stem: up to 8 chars
	mvi	c,8
fnp2:	mov	a,m
	ora	a
	jz	fnpok
	cpi	' '
	jz	fnpok
	cpi	'.'
	jz	fnpext
	mov	b,a
	mov	a,c
	ora	a
	mov	a,b
	jz	fnp3		; stem full: swallow silently
	cpi	'a'
	jc	fnst
	cpi	7Bh
	jnc	fnst
	ani	0DFh
fnst:	stax	d
	inx	d
	dcr	c
fnp3:	inx	h
	jmp	fnp2
fnpext:	inx	h
	lxi	d,FNAME+8	; extension: up to 3 chars
	mvi	c,3
fnp5:	mov	a,m
	ora	a
	jz	fnpok
	cpi	' '
	jz	fnpok
	mov	b,a
	mov	a,c
	ora	a
	mov	a,b
	jz	fnp6
	cpi	'a'
	jc	fnxst
	cpi	7Bh
	jnc	fnxst
	ani	0DFh
fnxst:	stax	d
	inx	d
	dcr	c
fnp6:	inx	h
	jmp	fnp5
fnpok:	xra	a
	ret
fnpbad:	stc
	ret

; Compare keyword at [DE] (zero-terminated) against [CMDP], case-
; insensitively. Match: carry clear, HL at the delimiter. Else carry.
kwcmp:	lhld	CMDP
kw1:	ldax	d
	ora	a
	jz	kwend
	mov	b,a
	mov	a,m
	cpi	'a'
	jc	kw2
	cpi	7Bh
	jnc	kw2
	ani	0DFh
kw2:	cmp	b
	jnz	kwno
	inx	h
	inx	d
	jmp	kw1
kwend:	mov	a,m
	ora	a
	jz	kwyes
	cpi	' '
	jz	kwyes
kwno:	stc
	ret
kwyes:	ora	a
	ret

; ----------------------------------------------------------- prompt
;
; Same shape and command set as machine/bios.asm's prompt loop: dir, type,
; run, ls /dev, config, bind.

prompt:	lxi	h,mprmpt
	call	puts
	lxi	h,LINE
	mvi	c,0
rdch:	call	getc
	cpi	0Dh
	jz	rdend
	cpi	08h
	jz	rdbs
	cpi	7Fh
	jz	rdbs
	cpi	20h
	jc	rdch
	mov	b,a
	mov	a,c
	cpi	31
	jnc	rdch
	mov	m,b
	inx	h
	inr	c
	mov	a,b
	call	putc
	jmp	rdch
rdbs:	mov	a,c
	ora	a
	jz	rdch
	dcr	c
	dcx	h
	mvi	a,08h
	call	putc
	mvi	a,' '
	call	putc
	mvi	a,08h
	call	putc
	jmp	rdch
rdend:	mvi	m,0
	call	crlf
	lxi	h,LINE
psp:	mov	a,m
	cpi	' '
	jnz	pchk
	inx	h
	jmp	psp
pchk:	ora	a
	jz	prompt
	shld	CMDP
	lxi	d,kwdir
	call	kwcmp
	jnc	c_dir
	lxi	d,kwtype
	call	kwcmp
	jnc	c_type
	lxi	d,kwrun
	call	kwcmp
	jnc	c_run
	lxi	d,kwcfg
	call	kwcmp
	jnc	c_cfg
	lxi	d,kwls
	call	kwcmp
	jnc	c_ls
	lxi	d,kwbind
	call	kwcmp
	jnc	c_bind
	lxi	h,munk
	call	puts
	jmp	prompt
c_dir:	call	dircmd
	jmp	prompt
c_type:	call	fnparse
	jc	c_use
	call	typecmd
	call	crlf
	jmp	prompt
c_run:	call	fnparse
	jc	c_use
	call	runcmd
	jmp	prompt
c_cfg:	call	cfgcmd
	jmp	prompt
c_ls:	call	skipsp
	shld	CMDP
	call	lscmd
	jmp	prompt
c_bind:	call	bindcmd
	jmp	prompt
c_use:	lxi	h,musage
	call	puts
	jmp	prompt

; ----------------------------------------------------------- data

; HELLO payload: machine id (filled from the config block), ROM version,
; then the self-test inventory, filled in at boot by hello.
HELLOP:	db	0,0,0,0
	db	0,1,0		; ROM version 0.1.0 -- this template's first cut
	db	0,0,0

kwdir:	db	'DIR',0
kwtype:	db	'TYPE',0
kwrun:	db	'RUN',0
kwls:	db	'LS',0
kwcfg:	db	'CONFIG',0
kwbind:	db	'BIND',0
kwdev:	db	'/DEV',0

; Synthetic command lines for the boot-time auto-demo (bootdemo above):
; zero-terminated, fed through kwcmp/fnparse exactly like typed input.
; DIR takes no argument, so it's dispatched without one of these.
DEMOTYP: db	'TYPE ABOUT.TXT',0
DEMORUN: db	'RUN HELLO.COM',0
DEMODIR: db	0		; CMDP just needs to be non-null; dircmd
				; itself takes no argument to parse

; JMP 0 / JMP bdoshim, copied to page zero by setp0 (task 4.2). Both
; targets are relocated-body (RAM) addresses -- see setp0's comment.
P0IMG:	db	0C3h
	dw	softrst
	db	0,0
	db	0C3h
	dw	bdoshim
P0LEN	equ	8

mbann:	db	0Dh,0Ah,'RetroNix ROM 0.1.0 - Model 4 boot ladder',0Dh,0Ah,0
mcbbad:	db	'config block unreadable - local-only mode',0Dh,0Ah,0
mlink:	db	'link up: drive ',0
mlink2:	db	': bound',0Dh,0Ah,0
mlink0:	db	'link up: no network drives bound',0Dh,0Ah,0
mnosrv:	db	'no server link - local-only mode',0Dh,0Ah,0
mprmpt:	db	'retronix> ',0
munk:	db	'unknown command (try: dir, ls, type, run, config, bind)'
	db	0Dh,0Ah,0
musage:	db	'usage: type <file> | run <file> | ls /dev | config | bind'
	db	0Dh,0Ah,0
mnolnk:	db	'no server link',0Dh,0Ah,0
mwerr:	db	'wire error: no response',0Dh,0Ah,0
mserr:	db	'server error ',0
mnotf:	db	'file not found',0Dh,0Ah,0
mempty:	db	'empty file',0Dh,0Ah,0
mtoobg:	db	'file too big for TPA',0Dh,0Ah,0
mbig:	db	'64K+',0

mdemodir: db	'boot demo: dir',0Dh,0Ah,0
mdemotyp: db	'boot demo: type about.txt',0Dh,0Ah,0
mdemorun: db	'boot demo: run hello.com',0Dh,0Ah,0

mdev:	db	'/dev:',0Dh,0Ah,0
mdcpu:	db	'  cpu      ',0
mz80:	db	'z80',0
mdram:	db	'  ram      ',0
mkb:	db	' KB',0
mdcon:	db	'  console  video f800h-fbffh, keyboard matrix f400h-f7ffh',0
mdwire:	db	'  wire     tr1865, ports ',0
mdlink:	db	', link ',0
mup:	db	'up',0
mdown:	db	'down',0
mind:	db	'  ',0
munbnd:	db	'unbound',0
mdead:	db	' (dead)',0
mnobnd:	db	'  no network bindings',0Dh,0Ah,0
mlsdev:	db	'ls: only /dev is listable in this ROM version',0Dh,0Ah,0

mcfgb:	db	'config block: ',0
mcbok:	db	'valid, format v1, platform 02h (TRS-80 Model 4 / TR1865)',0
mcbno:	db	'UNREADABLE - unminted or corrupt',0
mcfgid:	db	'machine id:  ',0
mcfgrom:
	db	'rom version: ',0
mcfgl1:	db	'link config: tr1865, base ',0
mcfgl2:	db	', reset ',0
mcfgl3:	db	', mode ',0
mcfgl4:	db	', baud ',0
mcfgst:	db	'link state:  ',0
mlocal:	db	'local-only mode',0
mcfgmap:
	db	'drive map (the server profile owns it: change it there, '
	db	'reconciled at hello)',0Dh,0Ah,0

mbindok:
	db	'link up - bound drives:',0Dh,0Ah,0
mbnores:
	db	'bind failed: no response from the server',0Dh,0Ah,0
mbunk:	db	'bind refused: the server has no profile for this machine id'
	db	0Dh,0Ah,0
mbrefu:	db	'bind refused: server error ',0

; Keyboard decode table: 8 rows x 8 bits, unshifted only (see getc's
; comment). 0 = unmapped (a modifier, a blank position, or a key this
; driver doesn't decode).
KBTAB:
	db	'@','A','B','C','D','E','F','G'	; row 0
	db	'H','I','J','K','L','M','N','O'	; row 1
	db	'P','Q','R','S','T','U','V','W'	; row 2
	db	'X','Y','Z',0,0,0,0,0			; row 3
	db	'0','1','2','3','4','5','6','7'	; row 4
	db	'8','9',':',';',',','-','.','/'	; row 5
	db	0Dh,08h,0,0,0,0,0,' '			; row 6: Enter,
							; Clear->BS, Break
							; and the arrows are
							; not decoded, Space
	db	0,0,0,0,0,0,0,0				; row 7: modifiers only

CKSUM:	ds	1
TOUT:	ds	1
FUNC:	ds	1
RFN:	ds	1
RIDX:	ds	1
RCNT:	ds	2
RPTR:	ds	2
RDST:	ds	2
TRIES:	ds	1
PPTR:	ds	2
PLEN:	ds	1
INVCPU:	ds	1
INVRAM:	ds	1
INVSER:	ds	1
LINKUP:	ds	1
CBVFLG:	ds	1
MAPCNT:	ds	1
DEFDRV:	ds	1
CMDP:	ds	2
HERR:	ds	1
SPTR:	ds	2
DPTR:	ds	2
MWALK:	ds	1
PDRV:	ds	1
NLEN:	ds	1
DIDX:	ds	1
DFDRV:	ds	1
VCUR:	ds	2
KBCHR:	ds	1
WPORTB:	ds	1
WLRESET: ds	1
WLMODE:	ds	1
WLBAUD:	ds	1
DIRP:	ds	1		; dircmd's 1-byte DIR request (drive index)
DCNT:	ds	1		; dircmd: entries left to print
ENTP:	ds	2		; dircmd: cursor into the DIR response
FNAME:	ds	11		; fnparse's output: 8.3, space-padded, upcased
FRQ:	ds	18		; setfrq's FREAD request (drive+name+offset+len)
LINE:	ds	32
DMAP:	ds	DMAPN*DENTSZ
RBUF:	ds	512
TYPBUF:	ds	512		; one FREAD chunk for typecmd

	dephase
imgend	equ	$
IMGLEN	equ	imgend

	end
