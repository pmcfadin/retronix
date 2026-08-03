; RetroNix M1 machine image: BIOS bring-up + monitor + wire client +
; COM loader with a minimal BDOS console shim.
; 8080 instruction subset only — must run on every PRD target CPU; the
; harness executes this under "set cpu 8080" so Z80-only opcodes fault.
;
; Memory map (CP/M-shaped so genuine COM binaries run unmodified):
;   0000  JMP cold          (program JMP 0 = full reboot)
;   0003  iobyte, 0004 drive/user
;   0005  JMP bdoshim       (the canonical BDOS entry)
;   0100  TPA, up to TPATOP
;   E000  monitor + BIOS (this file's main body)
;   FE00  stack top
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
TPA	equ	0100h
TPATOP	equ	0E000h		; first byte the TPA must not touch

; ------------------------------------------------------ vector page

	org	0

	jmp	cold		; 0000: reboot
	db	0		; 0003: iobyte
	db	0		; 0004: current drive/user
	jmp	bdoshim		; 0005: BDOS entry for loaded programs

; ------------------------------------------------------ monitor body

	org	0E000h

cold:	di
	lxi	sp,STACK
	mvi	a,WRESET	; wire ACIA first: raising RTS/DTR starts
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
; (save/restore, so probing through live regions is safe).
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
	call	sadd		; length high byte: requests stay small
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

; Receive frame. Payload routing: bytes 0..2 (result + 16-bit count on
; data verbs) land in RBUF; bytes 3.. stream to [RDST] — which is how
; FREAD payloads reach the TPA directly, no bounce copy (M1 design).
; Carry set on timeout, bad version, or checksum failure.
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
	mov	b,a		; the byte
	lda	RIDX
	cpi	3
	jnc	rcvhi
	mov	e,a		; low bytes -> RBUF[idx]
	mvi	d,0
	lxi	h,RBUF
	dad	d
	mov	m,b
	lda	RIDX
	inr	a
	sta	RIDX
	jmp	rcvlp
rcvhi:	lhld	RPTR		; the rest -> caller's destination
	mov	m,b
	inx	h
	shld	RPTR
	jmp	rcvlp
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
	lxi	h,RBUF+3
	shld	RDST
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

; ------------------------------------------------------------ fread

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

; ------------------------------------------------------------- type

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

; -------------------------------------------------------------- run

runcmd:	lda	LINKUP
	ora	a
	jnz	run0
	lxi	h,mnolnk
	jmp	puts
run0:	call	setfrq
	lxi	h,TPA
	shld	RDST
runlp:	lda	RDST+1		; dest + 512 must stay under TPATOP
	cpi	0DEh
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

; ---------------------------------------------------- error prints

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

; -------------------------------------------------------- bdos shim

; Minimal console-only BDOS (M1 design): 0=warm boot, 1=conin+echo,
; 2=conout, 9=print $-string, 11=console status. Anything else gets
; an honest 0FFh, never fake success. Convention: result in A and L.
bdoshim:
	mov	a,c
	ora	a
	jz	warmret
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
	call	putc		; fn 1 echoes
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
bd11:	in	CONSS
	ani	CRDY
	jz	bd11n
	mvi	a,0FFh
	mov	l,a
	ret
bd11n:	xra	a
	mov	l,a
	ret

warmret:
	lxi	sp,STACK	; monitor stack back, program's is gone
	call	crlf
	jmp	prompt

; ------------------------------------------------------- utilities

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
c_use:	lxi	h,musage
	call	puts
	jmp	prompt

; ----------------------------------------------------------- data

; HELLO payload: machine id 1001 LE, ROM 0.2.0, inventory (filled at boot)
HELLOP:	db	0E9h,03h,00h,00h
	db	0,2,0
	db	0,0,0

kwdir:	db	'DIR',0
kwtype:	db	'TYPE',0
kwrun:	db	'RUN',0

mbann:	db	0Dh,0Ah,'RetroNix ROM 0.2.0 - M1 filesystem',0Dh,0Ah,0
mlink:	db	'link up: drive ',0
mlink2:	db	': bound',0Dh,0Ah,0
mnosrv:	db	'no server link - local-only mode',0Dh,0Ah,0
mprmpt:	db	'retronix> ',0
munk:	db	'unknown command (try: dir, type, run)',0Dh,0Ah,0
musage:	db	'usage: type <file> | run <file>',0Dh,0Ah,0
mnolnk:	db	'no server link',0Dh,0Ah,0
mwerr:	db	'wire error: no response',0Dh,0Ah,0
mserr:	db	'server error ',0
mnotf:	db	'file not found',0Dh,0Ah,0
mempty:	db	'empty file',0Dh,0Ah,0
mtoobg:	db	'file too big for TPA',0Dh,0Ah,0
mbig:	db	'64K+',0

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
LINKUP:	ds	1
MAPCNT:	ds	1
DEFDRV:	ds	1
DIRP:	ds	1
DCNT:	ds	1
ENTP:	ds	2
CMDP:	ds	2
FNAME:	ds	11
FRQ:	ds	18
LINE:	ds	32
RBUF:	ds	256
TYPBUF:	ds	512

	end
