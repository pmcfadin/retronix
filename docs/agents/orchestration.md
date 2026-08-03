# Orchestration: subareas, subagents, and skills

The main session is an **orchestrator, not an implementer**. It plans,
delegates, reviews reports, archives, and commits. Substantive work runs in
Opus subagents scoped to one subarea each, briefed to read their inputs from
disk (OpenSpec change artifacts, specs, ADRs) rather than having content
pasted into prompts.

## Subareas

| Subarea | Owns | Typical agent brief |
|---|---|---|
| **protocol** | `machine/protocol.inc` + `server/protocol.py` (lockstep pair) | Add verbs/codes to both files + framing unit tests |
| **server** | `server/` | Handlers, volumes, profiles, oracle log — test-first |
| **machine** | `machine/` | 8080-subset assembly; must keep `set cpu 8080` clean |
| **harness** | `harness/`, SIMH configs | Scenarios, oracle assertions, teardown proofs |
| **specs & domain** | `openspec/`, `docs/adr/`, `CONTEXT.md` | Artifact drafting, glossary/ADR upkeep |
| **docs & proofs** | `README.md`, `docs/RetroNix-PRD.md` | Proof sections, PRD sync after decisions |

Dependency order inside a milestone: **protocol → (server ∥ machine) →
harness → review**. Server and machine subagents can run in parallel once
the protocol constants exist; the harness agent goes last because it needs
both sides live. Only one agent runs SIMH at a time (the scenarios are
timing-sensitive under CPU contention).

## Per-milestone flow

1. **Decide** (main session): `/mattpocock-skills:grilling` or
   `/mattpocock-skills:grill-with-docs` for anything architecturally open;
   outcomes land in `docs/adr/` and `CONTEXT.md` via domain-modeling.
2. **Propose** (main session or a specs subagent): `/opsx:propose` — the
   change artifacts are the subagents' work orders, so write task groups to
   align with subareas.
3. **Build** (Opus subagents, one per subarea): each brief names the change
   (`openspec/changes/<id>/`), the task group, the files it may touch, and
   the command that proves its slice (e.g. `make test`, `make image`).
   Agents report summaries; they do not commit.
4. **Verify** (subagents): one agent runs the full harness proof
   (`python3 harness/run_proof.py --runs 10`); in parallel,
   `/mattpocock-skills:code-review` reviews the diff since the milestone's
   base commit — its Spec axis reads the OpenSpec change per
   `issue-tracker.md`.
5. **Close** (main session): review reports, fix or re-delegate findings,
   `/opsx:archive`, commit, push.

## Which skill for what

- `mattpocock-skills:research` — background research agent for primary-source
  facts (SIMH device behavior, CP/M internals, CP/NET framing, real-hardware
  specifics for M5); writes findings as markdown into the repo.
- `mattpocock-skills:tdd` — server-side task groups (Python is cheap to
  test-first; assembly is not).
- `mattpocock-skills:prototype` — throwaway spikes for open design questions
  (e.g. trying a wire-protocol variant against the emulator).
- `mattpocock-skills:diagnosing-bugs` — when a harness scenario goes red for
  non-obvious reasons.
- `mattpocock-skills:codebase-design` — before adding a new module seam
  (e.g. when the redirector lands).
- `simplify` / `/code-review` — quality and correctness passes before archive.

## Context discipline

- Briefs point at files; they never inline file contents the agent can read.
- Agents return **conclusions and deltas**, not transcripts or file dumps.
- The main session re-verifies cheaply (validate, `make test`, targeted
  greps) instead of re-reading whole files.
