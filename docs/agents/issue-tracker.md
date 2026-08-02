# Issue tracker: OpenSpec

Work for this repo is tracked as **OpenSpec changes**, not GitHub issues. The
source of truth for "what was asked" is `openspec/changes/<change-id>/`
(proposal, spec deltas, tasks); the source of truth for current behavior is
`openspec/specs/`. Completed changes are archived and their deltas merged into
the main specs.

Use the `openspec` CLI (v1.5+) for all operations; slash commands under
`/opsx:*` wrap the full workflows.

## Conventions

- **Create an issue / ticket / PRD**: create an OpenSpec change proposal —
  `/opsx:propose "<idea>"`, or scaffold by hand under
  `openspec/changes/<change-id>/` with a `proposal.md`, spec deltas in
  `specs/`, and a `tasks.md` checklist. Validate with
  `openspec validate <change-id>`.
- **Read an issue**: `openspec show <change-id>` (or read
  `openspec/changes/<change-id>/` directly).
- **List issues**: `openspec list` for open changes; `openspec list --specs`
  for current specs.
- **Work state**: `openspec status --change <change-id>` shows artifact
  completion; `tasks.md` checkboxes are the task-level state.
- **Comment on an issue**: append a dated note to the change's `proposal.md`
  (there is no separate comment stream).
- **Close**: complete the tasks, then `/opsx:archive` (or
  `openspec archive <change-id>`) — this merges the spec deltas into
  `openspec/specs/` and moves the change to the archive.

## When a skill says "publish to the issue tracker"

Create an OpenSpec change proposal (`/opsx:propose`). One change per coherent
unit of work; the proposal.md carries what a GitHub issue body would.

## When a skill says "fetch the relevant ticket"

Run `openspec show <change-id>` and read the change folder — `proposal.md` for
intent, `specs/` deltas for requirements, `tasks.md` for scope.

## Spec review (code-review's Spec axis)

Review implementation diffs against the change's **spec deltas**
(`openspec/changes/<change-id>/specs/`), falling back to `proposal.md` for
intent. `openspec/specs/` describes pre-change behavior and is only updated at
archive time — never treat it as the target state while a change is in flight.

## PRs as a request surface

**No.** External PRs are not part of the triage queue for this repo.
