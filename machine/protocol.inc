; RetroNix wire protocol v0 — machine-side constants.
; Mirrored in server/protocol.py; the two files MUST stay in lockstep.
; Frame shape and semantics: ADR-0003. HELLO reconciliation: ADR-0005.
;
; Frame: [version][function][len-lo][len-hi][payload...][checksum]
; checksum = two's complement of the 8-bit sum of every preceding byte,
; so summing an entire frame (checksum included) yields 0.

PVER	equ	01h		; protocol version 0 wire tag

; Function codes — requests (machine -> server)
FHELLO	equ	01h
FDIR	equ	02h
FREAD	equ	03h

; Responses carry (request code | 80h); payload byte 0 is the result code.
FRESP	equ	80h		; OR-mask for response function codes
FERR	equ	0ffh		; bad-frame response (request code unknowable)

; Result codes — closed v0 table
ROK	equ	00h
RBADFRM	equ	01h		; checksum/length failure
RUNKMCH	equ	02h		; HELLO from a machine ID with no profile
RUNBND	equ	03h		; DIR for a drive letter the map does not bind
RBADREQ	equ	04h		; well-framed but malformed payload
RFNF	equ	05h		; FREAD for a file absent from the volume

; FREAD request payload — 18 bytes:
;   drive index (1), name 8 + ext 3 space-padded (11),
;   offset 4 little-endian, length 2 little-endian
; FREAD OK payload: [ROK][actual-lo][actual-hi][bytes...]

; HELLO request payload — 10 bytes
;   machine id     4 bytes little-endian
;   rom version    3 bytes (major, minor, patch)
;   inventory      3 bytes (cpu type: 0=8080 1=Z80; ram KB; serial: 1=up)
;
; HELLO OK payload: [ROK][count][entries...]
;   entry: drive index (0=A..15=P), kind (0=network), flags (bit0=read-only),
;          name length, volume name bytes
;
; DIR request payload — 1 byte: drive index
; DIR OK payload: [ROK][count-lo][count-hi][entries...]
;   entry: name 8 bytes space-padded, ext 3 bytes space-padded,
;          size 4 bytes little-endian  (15 bytes per entry)

RETRIES	equ	3		; bounded retry per request (ADR-0003)
