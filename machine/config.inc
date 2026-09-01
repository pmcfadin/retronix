; RetroNix config block v1 — machine-side constants (task 3.1).
; Mirrored in server/configblock.py; the two files MUST stay in lockstep —
; server/tests/test_config_inc_pins.py parses this file and asserts every
; offset/length below against that module's values.
;
; One fixed-layout, fixed-address region per ROM template, stamped by the
; foundry and read by the BIOS at cold boot, before the wire is touched
; (ADR-0006, openspec/changes/m3-foundry/design.md "Config block v1
; layout"). Offsets are from the block's own base, CFGBLK.
;
; The checksum is the wire's rule reused verbatim (protocol.inc): two's
; complement of the 8-bit sum of the defined bytes, so summing the whole
; defined block (checksum byte included) yields zero.

CFGBLK	equ	0E100h		; block base -- design.md "Where the block
				; lives": org 0E000h holds a jmp to the
				; monitor body relocated to 0E300h, so the
				; block sits at this round address between
				; the two, reserved with `ds CFGBLKRES`.

CFG_VERSION	equ	01h	; block format version this ROM understands

; Platform ids (design.md's table).
CFG_PLAT_ALTAIR	equ	01h	; MITS Altair 8800 / M2SIO ACIA
CFG_PLAT_MODEL4	equ	02h	; TRS-80 Model 4 / TR1865

; Profile state at mint time.
CFG_ST_PROBE	equ	00h
CFG_ST_EXACT	equ	01h

; -- field offsets, from CFGBLK -----------------------------------------
; design.md's table, verbatim; must match server/configblock.py's OFF_*/
; LEN_* constants line for line (the pin test checks this).
CFG_OFF_MAGIC	equ	000h
CFG_LEN_MAGIC	equ	4
CFG_OFF_VERSION	equ	004h
CFG_LEN_VERSION	equ	1
CFG_OFF_PLATFORM equ	005h
CFG_LEN_PLATFORM equ	1
CFG_OFF_MACHID	equ	006h	; machine id, 32-bit little-endian
CFG_LEN_MACHID	equ	4
CFG_OFF_LINK	equ	00Ah	; port base, reset, mode, baud, 4 reserved
CFG_LEN_LINK	equ	8
CFG_OFF_MAPCNT	equ	012h	; cached map entry count, 0-16
CFG_LEN_MAPCNT	equ	1
CFG_OFF_STATE	equ	013h	; profile state at mint -- 00 probe, 01 exact
CFG_LEN_STATE	equ	1
CFG_OFF_RESVD	equ	014h	; reserved, zero
CFG_LEN_RESVD	equ	12
CFG_OFF_MAP	equ	020h	; cached drive map: DMAPN entries of DENTSZ
CFG_LEN_MAP	equ	320	; bytes each -- exactly DMAP's own shape
CFG_OFF_CKSUM	equ	160h
CFG_LEN_CKSUM	equ	1

; Bytes 0x000-0x160 inclusive (353 bytes) are defined; the checksum covers
; exactly this range. The template reserves CFGBLKRES bytes at CFGBLK with
; the tail beyond CFGBLKLEN zero-filled, so a v2 block can grow without
; moving anything.
CFGBLKLEN	equ	0161h	; CFG_OFF_CKSUM + CFG_LEN_CKSUM = 353
CFGBLKRES	equ	0200h	; 512: E100h..E300h, the whole gap to the body
