# The shell namespace is /<drive>/<file> — no fake hierarchy

The Unix surface presents each drive letter as a top-level directory
(`/a`, `/b`, or a friendly alias from the drive map), exactly two levels
deep, plus a synthetic read-only `/dev` showing the self-test inventory and
bind state. The shell accepts both `/b/readme.txt` and `b:readme.txt`,
displays lowercase, and translates to uppercase FCB names underneath. COM
programs receive command tails in CP/M form, untranslated — the Unix idiom
is the shell's dialect, not an OS-wide translation layer.

Deeper hierarchy on network volumes was rejected for v1 even though the
server has real directories: it would make network drives semantically
different from local ones, breaking ADR-0001's invariant that CP/M cannot
tell the difference, and simulating subdirectories over CP/M's flat
filesystem misrepresents what the machine is.
