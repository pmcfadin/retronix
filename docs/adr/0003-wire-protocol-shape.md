# Wire protocol: machine-initiated, one outstanding request, binary frames, idempotent verbs

The serial protocol is strict request/response: the machine initiates every
exchange, the server never speaks unprompted, and there is exactly one
outstanding request at a time. Frames are length-prefixed binary — a fixed
header modeled on CP/NET's (format/version byte, function code, 16-bit
payload length), raw payload, checksum — never escaped, so COM binaries
transfer without XMODEM-style encoding. Errors are in-band response codes
the redirector maps onto honest BDOS error returns.

Timeout and bounded retry live in the redirector, so **every verb must be
idempotent**: write verbs carry explicit offsets, and the server never
tracks file positions or any per-connection cursor. This constrains all
future verbs, including foundry and library operations.

A human-readable text-line protocol was rejected: it needs escaping for
binary payloads, and the test oracle is the server's structured log, not a
terminal, so eyeball-debuggability buys little.
