# RetroNix

RetroNix is a custom CP/M BIOS plus a Unix-flavored shell for real 8080/Z80
hardware, backed by a serial-connected server. The PRD lives at
`docs/RetroNix-PRD.md`.

## Agent skills

### Orchestration

The main session orchestrates; Opus subagents implement, scoped one per
subarea (protocol, server, machine, harness, specs, docs). See
`docs/agents/orchestration.md` for the subarea map, per-milestone flow, and
which Matt Pocock skill applies where.

### Issue tracker

Work is tracked as OpenSpec changes (`openspec/changes/`), managed via the `openspec` CLI and `/opsx:*` commands. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
