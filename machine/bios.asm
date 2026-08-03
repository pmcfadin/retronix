; RetroNix M2 machine image: BIOS bring-up + monitor + wire client +
; COM loader with a minimal BDOS console shim.
;
; The Boot Ladder is inspectable and leavable from the prompt:
;   dir / type / run   the M1 wire verbs, on the default network drive
;   ls /dev            synthetic read-only inventory: self-test devices
;                      and every drive letter's bind state (ADR-0004)
;   config             machine ID, ROM version, burned-in link config,
;                      link state, and the whole retained Drive Map
;   bind               re-runs the HELLO rung on demand, so recovering a
;                      dead bind costs one command, not a reboot
; The complete Drive Map the server returns is retained (see DMAP), which
; is what lets ls and config tell the truth about every binding.
;
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
WCARR	equ	0Ch		; /DCD + /CTS, active low: 0 = peer there

STACK	equ	0FE00h
TOUTER	equ	16		; outer x 65536 inner polls per byte timeout
WCOUT	equ	192		; same, for the carrier wait after a re-dial:
				; the dial is asynchronous and lands several
				; link polls later, well past a byte timeout
TPA	equ	0100h
TPATOP	equ	0E000h		; first byte the TPA must not touch

; Retained Drive Map: one fixed-stride entry per bound CP/M drive letter.
; Fixed stride buys index arithmetic instead of a linked walk, which is
; what the 8080 is good at; the cost is a truncation ceiling on names.
DMAPN	equ	16		; CP/M has exactly sixteen drive letters
DNAMEL	equ	16		; retained name maximum; longer is truncated
DENTSZ	equ	20		; drive, kind, flags, name length, DNAMEL name

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
	sta	MAPCNT
	mvi	a,0FFh
	sta	DEFDRV
	call	hello		; HELLO at boot; carry set = no link
	jc	lonly
	mvi	a,1
	sta	LINKUP
	lda	DEFDRV
	inr	a		; 0FFh -> 0: linked, but nothing bound
	jz	lbare		; a live link with an empty map is not
				; local-only mode
	lxi	h,mlink
	call	puts
	lda	DEFDRV
	adi	'A'
	call	putc
	lxi	h,mlink2
	call	puts
	jmp	prompt

lbare:	lxi	h,mlink0
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

; Send A over the wire; carry set on timeout. Transmit needs both a ready
; transmit register and carrier: the ACIA reports TDRE ready even with
; nobody on the far end, and a byte written then does not vanish — it sits
; in the line's transmit buffer and is delivered the instant the peer
; comes back, arriving *ahead* of the next frame and shifting it by one.
; The receiver of that stream reads a bogus length and waits forever. So a
; dead link must swallow no bytes at all: wait for carrier, or time out.
wtx:	mov	b,a
	mvi	a,TOUTER
	sta	TOUT
wtxo:	lxi	d,0
wtx1:	in	WSTAT
	ani	WTDRE+WCARR	; ready to send, and /DCD + /CTS both low
				; (disjoint bits, so the sum is the mask)
	cpi	WTDRE
	jz	wtx2
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
	xra	a		; nothing on the wire announces a dead
	sta	LINKUP		; server, so exhausted retries are how the
	stc			; machine learns. The retained map now
				; reads dead rather than stale-live.
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
	jnc	hresp
	mvi	a,0FFh		; no response at all — distinct from a
	sta	HERR		; refusal, so bind names the real reason
	stc
	ret
hresp:	lda	RBUF		; result code
	sta	HERR
	ora	a
	jz	hok
	stc
	ret

; Parse the whole response into the retained map — every binding, not just
; the first. The response lands contiguously at RBUF (rcvfrm routes bytes
; 0..2 there and 3.. to RDST, which hello set to RBUF+3):
;   [ROK][count][entry...]  entry = drive, kind, flags, namelen, name...
; Wire entries are variable-stride; the retained table is fixed-stride, so
; a name longer than DNAMEL is kept truncated rather than overrunning it.
hok:	mvi	a,0FFh
	sta	DEFDRV		; unclaimed: the first binding takes it
	lda	RBUF+1		; binding count
	cpi	DMAPN+1
	jc	hok1
	mvi	a,DMAPN		; more letters than CP/M has: keep the first 16
hok1:	sta	MAPCNT
	ora	a
	rz			; empty map: link up, nothing bound
	sta	MWALK
	lxi	h,RBUF+2
	shld	SPTR
	lxi	h,DMAP
	shld	DPTR
hoke:	lhld	SPTR
	mov	a,m		; drive index
	sta	PDRV
	inx	h
	inx	h
	inx	h
	mov	a,m		; name length as it came off the wire
	sta	NLEN
	lda	DEFDRV
	inr	a		; 0FFh -> 0
	jnz	hokc		; a default drive is already claimed
	lda	PDRV
	sta	DEFDRV		; first bound drive still names the default
hokc:	lhld	DPTR
	xchg			; DE = table entry
	lhld	SPTR		; HL = wire entry
	mvi	c,3
hokh:	mov	a,m		; drive, kind, flags copy straight across
	stax	d
	inx	h
	inx	d
	dcr	c
	jnz	hokh
	inx	h		; step over the wire name length
	lda	NLEN
	cpi	DNAMEL+1
	jc	hokn
	mvi	a,DNAMEL	; truncate: display table, not storage
hokn:	stax	d		; retained (possibly truncated) name length
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
hokp:	lhld	SPTR		; wire stride: 4 + untruncated name length
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

; ------------------------------------------------- drive map report

; Step DPTR to the next table entry and count one off MWALK. Zero flag
; set when the walk is done. Both walks over the fixed-stride table —
; the parse that fills it and the print that reads it — step with this,
; so the stride lives in exactly one place.
dnext:	lhld	DPTR
	lxi	d,DENTSZ
	dad	d
	shld	DPTR
	lda	MWALK
	dcr	a
	sta	MWALK
	ret

; Find the retained entry for drive index A. Carry clear and HL at the
; entry on a hit; carry set when no entry binds that letter at all.
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

; Print the volume name of the entry at HL, plus a dead marker when the
; map still holds the binding but the link is gone. That distinction is
; the whole point of keeping LINKUP honest.
pdent:	push	h
	inx	h
	inx	h
	inx	h
	mov	c,m		; retained name length
	inx	h		; HL = name bytes
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

; Print "  x: " for drive index A.
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

; Every CP/M drive letter with its bind state — bound volume, dead, or
; never bound. Touches no wire and no disk.
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

; Just the retained bindings, in the order the server sent them.
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

; --------------------------------------------------------------- ls

; /dev is synthetic and read-only (ADR-0004): generated from the boot
; self-test and the retained map, never a place files live.
lscmd:	lxi	d,kwdev
	call	kwcmp
	jnc	lsdev
	lxi	h,mlsdev
	jmp	puts

lsdev:	lxi	h,mdev
	call	puts
	lxi	h,mdcpu
	call	puts
	lda	INVCPU
	ora	a
	lxi	h,m8080
	jz	lsd1
	lxi	h,mz80
lsd1:	call	puts
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
	lxi	h,mdcon		; ports come from the equates the image was
	call	puts		; minted with, never from a literal, so a
	mvi	a,CONSS		; re-mint onto different hardware still
	call	phexp		; describes the machine it is actually on
	lxi	h,mdport
	call	puts
	mvi	a,CONSD
	call	phexp
	call	crlf
	lxi	h,mdwire
	call	puts
	mvi	a,WSTAT
	call	phexp
	lxi	h,mdport
	call	puts
	mvi	a,WDATA
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

; Reachable from every rung of the ladder: never touches the wire, so an
; unreachable server can't make config unreachable. Read-only in this ROM
; version, and says whose the Drive Map actually is (ADR-0005).
cfgcmd:	lxi	h,mcfgid
	call	puts
	call	pmid
	call	crlf
	lxi	h,mcfgrom
	call	puts
	call	prom
	call	crlf
	lxi	h,mcfgl1	; the burned-in link config, read back from the
	call	puts		; very equates the wire code uses
	mvi	a,WSTAT
	call	phexp
	mvi	a,'/'
	call	putc
	mvi	a,WDATA
	call	phexp
	lxi	h,mcfgl2
	call	puts
	mvi	a,WMODE		; the framing byte itself, so the decode beside
	call	phexp		; it can be checked rather than trusted
	lxi	h,mcfgl3
	call	puts
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

; Burned-in machine ID, 32-bit little-endian. Printed decimal while it
; fits sixteen bits, hex beyond that — a truncated decimal would lie.
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

; ------------------------------------------------------------- bind

; Re-runs the ladder's HELLO rung on demand: no reboot, no self-test, no
; second banner. The wire is settled and drained first — after a dropped
; link the ACIA can hold a stale byte, and "no response" should mean no
; response, not "we ate someone else's byte".
;
; Carrier first, re-init only as a last resort. The 6850 *latches* carrier
; loss: once the peer goes away the status bit stays set until the data
; register is read, so a link that has already come back still reads dead.
; Clearing that latch is what lets bind see the truth — and seeing the
; truth is what keeps it from master-resetting the ACIA, which drops
; RTS/DTR and tears down the very connection it was about to use.
bindcmd:
	in	WDATA		; clear the latched carrier loss
	call	wcwait		; then wait, bounded, for the real line state
	jnc	bindrn		; carrier: touch nothing, just talk
	mvi	a,WRESET	; nobody out there after a full wait, so there
	out	WSTAT		; is no connection left to lose: re-init to
	mvi	a,WMODE		; re-raise RTS/DTR and kick a fresh dial
	out	WSTAT
	in	WDATA
	call	wcwait		; a frame sent before the dial lands goes
				; on the floor unseen — the ACIA reports
				; TDRE ready with no peer at all
bindrn:	call	wdrain
	xra	a
	sta	LINKUP		; not linked again until this HELLO says so
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
	lxi	h,mbrefu	; some other code from the closed v0 table
	call	puts
	lda	HERR		; hex: '0'+code would garble anything past 9
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

; Wait, bounded, for the ACIA to show carrier. Carry set if it never
; came — bind still tries the HELLO, and reports the same honest silence.
wcwait:	mvi	a,WCOUT
	sta	TOUT
wcwo:	lxi	d,0
wcw1:	in	WSTAT
	ani	WCARR
	jz	wcw2
	dcx	d
	mov	a,d
	ora	e
	jnz	wcw1
	lda	TOUT
	dcr	a
	sta	TOUT
	jnz	wcwo
	stc
	ret
wcw2:	xra	a
	ret

; Swallow whatever the ACIA is still holding, bounded so a chattering
; peer can't trap us here.
wdrain:	lxi	d,512
wdr1:	in	WSTAT
	ani	WRDRF
	rz
	in	WDATA
	dcx	d
	mov	a,d
	ora	e
	jnz	wdr1
	ret

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

; Print A as a two-digit hex byte with the assembler's 'h' suffix, the
; way the equates that produced it are written.
phexp:	call	phex8
	mvi	a,'h'
	jmp	putc

; Print A as two hex digits.
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

; Advance HL past spaces.
skipsp:	mov	a,m
	cpi	' '
	rnz
	inx	h
	jmp	skipsp

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
	lxi	d,kwls
	call	kwcmp
	jnc	c_ls
	lxi	d,kwcfg
	call	kwcmp
	jnc	c_cfg
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
c_ls:	call	skipsp		; kwcmp left HL at the delimiter
	shld	CMDP		; lscmd matches its path argument from there
	call	lscmd
	jmp	prompt
c_cfg:	call	cfgcmd
	jmp	prompt
c_bind:	call	bindcmd
	jmp	prompt
c_use:	lxi	h,musage
	call	puts
	jmp	prompt

; ----------------------------------------------------------- data

; HELLO payload: machine id 1001 LE, ROM version, then the
; self-test inventory, filled in at boot by hello.
HELLOP:	db	0E9h,03h,00h,00h
	db	0,3,0
	db	0,0,0

kwdir:	db	'DIR',0
kwtype:	db	'TYPE',0
kwrun:	db	'RUN',0
kwls:	db	'LS',0
kwcfg:	db	'CONFIG',0
kwbind:	db	'BIND',0
kwdev:	db	'/DEV',0

mbann:	db	0Dh,0Ah,'RetroNix ROM 0.3.0 - M2 boot ladder',0Dh,0Ah,0
mlink:	db	'link up: drive ',0
mlink2:	db	': bound',0Dh,0Ah,0
mlink0:	db	'link up: no network drives bound',0Dh,0Ah,0
mnosrv:	db	'no server link - local-only mode',0Dh,0Ah,0
mprmpt:	db	'retronix> ',0
munk:	db	'unknown command (try: dir, ls, type, run, config, bind)'
	db	0Dh,0Ah,0
musage:	db	'usage: type <file> | run <file> | ls /dev | config | bind'
	db	0Dh,0Ah,0

mdev:	db	'/dev:',0Dh,0Ah,0
mdcpu:	db	'  cpu      ',0
m8080:	db	'8080',0
mz80:	db	'z80',0
mdram:	db	'  ram      ',0
mkb:	db	' KB',0
mdcon:	db	'  console  sio, status port ',0
mdwire:	db	'  wire     acia, status port ',0
mdport:	db	', data port ',0
mdlink:	db	', link ',0
mup:	db	'up',0
mdown:	db	'down',0
mind:	db	'  ',0
munbnd:	db	'unbound',0
mdead:	db	' (dead)',0
mnobnd:	db	'  no network bindings',0Dh,0Ah,0
mlsdev:	db	'ls: only /dev is listable in this ROM version',0Dh,0Ah,0

mcfgid:	db	'machine id:  ',0
mcfgrom:
	db	'rom version: ',0
mcfgl1:	db	'link config: wire acia, ports ',0
mcfgl2:	db	', mode ',0
; The decode below must track WMODE: 15h = 8 data bits, no parity,
; 1 stop bit, /16 clock. The byte itself is printed beside it.
mcfgl3:	db	' (8N1 /16), machine-initiated',0Dh,0Ah,0
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
HERR:	ds	1		; last HELLO: 0 ok, 0FFh silent, else code
SPTR:	ds	2		; map parse: cursor into the wire response
DPTR:	ds	2		; map walk: cursor into DMAP (see dnext)
MWALK:	ds	1		; map walk: entries still to go (see dnext)
PDRV:	ds	1		; map parse: drive index of the entry in hand
NLEN:	ds	1		; map parse: name length as sent on the wire
DIDX:	ds	1		; /dev: drive letter being printed
DFDRV:	ds	1		; dfind: drive index being looked for
FNAME:	ds	11
FRQ:	ds	18
LINE:	ds	32
DMAP:	ds	DMAPN*DENTSZ	; the retained Drive Map
RBUF:	ds	512		; sized so a 16-binding HELLO cannot overrun
TYPBUF:	ds	512

	end
