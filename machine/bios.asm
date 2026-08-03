; RetroNix M0 machine image: BIOS bring-up + monitor + wire client.
; 8080 instruction subset only — must run on every PRD target CPU; the
; harness executes this under "set cpu 8080" so Z80-only opcodes fault.
;
; Devices (SIMH AltairZ80):
;   console: SIO line 0, status 10h (bit0 rx, bit1 tx), data 11h
;   wire:    M2SIO1 ACIA, status/ctl 12h (bit0 RDRF, bit1 TDRE), data 13h
;
; Link config and machine ID are assembled-in constants — the image is
; born configured (ADR-0005, in miniature).

	.8080

	include 'machine/protocol.inc'

CONSS	equ	10h		; console status port
CONSD	equ	11h		; console data port
CRDY	equ	01h		; console rx ready
CTXR	equ	02h		; console tx ready

WSTAT	equ	12h		; wire ACIA status/control
WDATA	equ	13h		; wire ACIA data
WRDRF	equ	01h		; wire rx ready
WTDRE	equ	02h		; wire tx ready
WRESET	equ	03h		; ACIA master reset
WMODE	equ	15h		; 8N1, /16 clock

STACK	equ	0FE00h
TOUTER	equ	16		; outer x 65536 inner polls per byte timeout

	org	0

	di
	lxi	sp,STACK
	jmp	start

; ---------------------------------------------------------------- boot

start:	mvi	a,WRESET	; wire ACIA first: raising RTS/DTR starts
	out	WSTAT		; the (async) link bring-up while we boot
	mvi	a,WMODE
	out	WSTAT
	lxi	h,mbann		; banner: first visible act after power-on
	call	puts
	call	cpudet		; self-test inventory
	sta	INVCPU
	call	ramsz
	sta	INVRAM
	xra	a
	sta	LINKUP
	mvi	a,0FFh
	sta	DEFDRV
	call	hello		; HELLO at boot; carry set = no link
	jc	lonly
	mvi	a,1
	sta	LINKUP
	lxi	h,mlink
	call	puts
	lda	DEFDRV
	adi	'A'
	call	putc
	lxi	h,mlink2
	call	puts
	jmp	prompt

lonly:	lxi	h,mnosrv	; never a dead end: local-only prompt
	call	puts
	jmp	prompt

; ------------------------------------------------------- self-test

; CPU type -> A: 0 = 8080, 1 = Z80. The 8080 always keeps flag bit 1
; set; the Z80 uses it as N and clears it after XRA.
cpudet:	xra	a
	push	psw
	pop	b		; C = flags
	mov	a,c
	ani	02h
	mvi	a,0
	rnz			; bit set -> 8080
	mvi	a,1
	ret

; RAM size in KB -> A. Probes the last byte of each KB from 16 KB up
; (the image itself owns the bottom, so 16 KB is the honest floor).
ramsz:	mvi	c,16
	lxi	h,3FFFh
rmlp:	mov	b,m
	mvi	m,55h
	mov	a,m
	cpi	55h
	jnz	rmfail
	mvi	m,0AAh
	mov	a,m
	cpi	0AAh
	jnz	rmfail
	mov	m,b
	mov	a,c
	cpi	64
	jz	rmdone
	inr	c
	mov	a,h
	adi	4
	mov	h,a
	jmp	rmlp
rmfail:	dcr	c
rmdone:	mov	a,c
	ret

; ------------------------------------------------------- console io

putc:	push	psw
putc1:	in	CONSS
	ani	CTXR
	jz	putc1
	pop	psw
	out	CONSD
	ret

puts:	mov	a,m
	ora	a
	rz
	call	putc
	inx	h
	jmp	puts

getc:	in	CONSS
	ani	CRDY
	jz	getc
	in	CONSD
	ani	7Fh
	ret

crlf:	mvi	a,0Dh
	call	putc
	mvi	a,0Ah
	jmp	putc

; ------------------------------------------------------- wire bytes

; Send A over the wire; carry set on timeout. TDRE stays low when the
; server is down, so sends time out exactly like receives. The timeout
; must also outlast the async TCP dial the ACIA init kicked off.
wtx:	mov	b,a
	mvi	a,TOUTER
	sta	TOUT
wtxo:	lxi	d,0
wtx1:	in	WSTAT
	ani	WTDRE
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
	out	WDATA
	ora	a
	ret

; Receive a byte -> A; carry set on timeout.
wrx:	mvi	a,TOUTER
	sta	TOUT
wrxo:	lxi	d,0
wrx1:	in	WSTAT
	ani	WRDRF
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
wrx2:	in	WDATA
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

; Send frame: function in FUNC, payload at HL, length in C (<=255).
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
	call	sadd		; length high byte: 0 in M0
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
	inr	a		; two's complement: frame sums to zero
	jmp	wtx

; Receive frame into RBUF; RFN/RLEN filled. Carry set on timeout,
; bad version, oversize, or checksum failure.
rcvfrm:	xra	a
	sta	CKSUM
	call	wrxs
	rc
	cpi	PVER
	jnz	rcvbad
	call	wrxs
	rc
	sta	RFN
	call	wrxs
	rc
	sta	RLEN
	call	wrxs
	rc
	ora	a
	jnz	rcvbad		; >255 payload: beyond M0 buffers
	lda	RLEN
	mov	c,a
	lxi	h,RBUF
	ora	a
	jz	rcvck
rcvlp:	call	wrxs
	rc
	mov	m,a
	inx	h
	dcr	c
	jnz	rcvlp
rcvck:	call	wrxs		; checksum byte joins the sum
	rc
	lda	CKSUM
	ora	a
	jnz	rcvbad
	ret
rcvbad:	stc
	ret

; Request/response with bounded retry (ADR-0003: verbs are idempotent,
; so a resend after a lost response is always safe).
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
	stc
	ret
rpcok:	xra	a
	ret

; ------------------------------------------------------------ hello

hello:	lda	INVCPU
	sta	HELLOP+7
	lda	INVRAM
	sta	HELLOP+8
	mvi	a,1
	sta	HELLOP+9
	mvi	a,FHELLO
	sta	FUNC
	lxi	h,HELLOP
	shld	PPTR
	mvi	a,10
	sta	PLEN
	call	rpc
	rc
	lda	RBUF		; result code
	ora	a
	jz	hok
	stc
	ret
hok:	lda	RBUF+1		; binding count
	sta	MAPCNT
	ora	a
	rz			; empty map: link up, nothing bound
	lda	RBUF+2		; first binding's drive index
	sta	DEFDRV
	xra	a
	ret

; -------------------------------------------------------------- dir

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
	call	rpc
	jnc	dir1
	lxi	h,mwerr
	jmp	puts
dir1:	lda	RBUF
	ora	a
	jz	dir2
	lxi	h,mserr		; honest in-band error, code included
	call	puts
	lda	RBUF
	adi	'0'
	call	putc
	jmp	crlf
dir2:	lda	RBUF+1		; entry count (low byte; <=16 fits M0 frames)
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

; Print C bytes from HL, skipping pad spaces.
putfn:	mov	a,m
	cpi	' '
	jz	pfn1
	call	putc
pfn1:	inx	h
	dcr	c
	jnz	putfn
	ret

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
pdgend:	mov	a,e		; undo overshoot: HL += -DE
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
	rnz			; still suppressing leading zeros
	mov	a,c
	jmp	putc
pdgpr:	mvi	b,0
	mov	a,c
	jmp	putc

; ----------------------------------------------------------- prompt

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
	jc	rdch		; ignore other control chars
	mov	b,a
	mov	a,c
	cpi	31
	jnc	rdch		; buffer full
	mov	m,b
	inx	h
	inr	c
	mov	a,b
	call	putc		; echo
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
psp:	mov	a,m		; skip leading spaces
	cpi	' '
	jnz	pchk
	inx	h
	jmp	psp
pchk:	ora	a
	jz	prompt		; empty line
	ani	0DFh
	cpi	'D'
	jnz	punk
	inx	h
	mov	a,m
	ani	0DFh
	cpi	'I'
	jnz	punk
	inx	h
	mov	a,m
	ani	0DFh
	cpi	'R'
	jnz	punk
	inx	h
	mov	a,m
	ora	a
	jz	pdir
	cpi	' '
	jz	pdir
punk:	lxi	h,munk
	call	puts
	jmp	prompt
pdir:	call	dircmd
	jmp	prompt

; ----------------------------------------------------------- data

; HELLO payload: machine id 1001 LE, ROM 0.1.0, inventory (filled at boot)
HELLOP:	db	0E9h,03h,00h,00h
	db	0,1,0
	db	0,0,0

mbann:	db	0Dh,0Ah,'RetroNix ROM 0.1.0 - M0 spine',0Dh,0Ah,0
mlink:	db	'link up: drive ',0
mlink2:	db	': bound',0Dh,0Ah,0
mnosrv:	db	'no server link - local-only mode',0Dh,0Ah,0
mprmpt:	db	'retronix> ',0
munk:	db	'unknown command (try: dir)',0Dh,0Ah,0
mnolnk:	db	'no server link',0Dh,0Ah,0
mwerr:	db	'wire error: no response',0Dh,0Ah,0
mserr:	db	'server error ',0
mbig:	db	'64K+',0

CKSUM:	ds	1
TOUT:	ds	1
FUNC:	ds	1
RFN:	ds	1
RLEN:	ds	1
TRIES:	ds	1
PPTR:	ds	2
PLEN:	ds	1
INVCPU:	ds	1
INVRAM:	ds	1
LINKUP:	ds	1
MAPCNT:	ds	1
DEFDRV:	ds	1
DIRP:	ds	1
DCNT:	ds	1
ENTP:	ds	2
LINE:	ds	32
RBUF:	ds	256

	end
