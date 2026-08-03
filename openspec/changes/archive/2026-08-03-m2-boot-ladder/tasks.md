# M2 Boot Ladder — Tasks

Groups map onto the subareas in `docs/agents/orchestration.md` and are
ordered by dependency: protocol → machine → harness. Group 1 is small and
independent; group 3 needs group 2's image to exist.

## 1. Protocol

- [x] 1.1 Document repeat-HELLO semantics (re-issuable on an established or
  reconnected session, idempotent, answered with the current drive map) in
  the comment headers of `machine/protocol.inc` and `server/protocol.py`,
  keeping the two files in lockstep. No new function or result codes.
- [x] 1.2 Add a regression test in `server/tests/test_handlers.py` pinning
  two HELLOs on one session: both ok, both carrying the drive map, session
  still usable for DIR afterwards. `make test` green.

## 2. Machine

- [x] 2.1 Enlarge `RBUF` to 512 bytes and add the retained drive-map table
  (16 fixed-stride entries: drive index, kind, flags, name length, 16 name
  bytes); confirm the listing's end address still clears the stack.
- [x] 2.2 Parse the full HELLO response into the table — every binding, not
  just the first — truncating volume names to the retained maximum;
  `DEFDRV` keeps naming the first bound drive so `dir`/`type`/`run` behave
  exactly as they did in M1.
- [x] 2.3 Clear `LINKUP` when a wire request exhausts its retries, so a
  binding the map still holds reads as dead rather than live.
- [x] 2.4 Implement `ls`: `/dev` prints the self-test devices (CPU, RAM,
  console, wire with link state) and one line per drive letter with its
  bind state (volume name / dead / unbound), touching no wire and no disk;
  any other path gets the honest "only /dev in this ROM version" reply.
- [x] 2.5 Implement `config`: machine ID, ROM version, burned-in link
  config, link state, and the full retained map with bind states; works in
  local-only mode, sends nothing on the wire, changes nothing, and names
  the server as the map's authority.
- [x] 2.6 Implement `bind`: re-init and drain the wire, re-issue HELLO with
  the boot inventory, replace the retained map on success, report the
  honest reason on failure (no response, or the server's error code), and
  return to the prompt in both cases without reboot, self-test, or banner.
- [x] 2.7 Extend the prompt parser with the three verbs and refresh the
  unknown-command and usage text; rebuild strict-8080 and confirm the five
  existing harness scenarios still pass unchanged.

## 3. Harness

- [x] 3.1 Verify whether AltairZ80's M2SIO re-establishes its outbound
  connection after the server closes it (design.md, first risk); record the
  answer and pick the recovery scenario's shape accordingly.
- [x] 3.2 Add mid-run server control to `Scenario`: a console-watcher thread
  that fires callbacks on marker text, plus stop/restart on the same port
  and the same oracle log, with teardown still killing whichever server is
  alive.
- [x] 3.3 Add the `/dev` scenarios — linked and local-only — asserting the
  device lines and bind states on the console and that the oracle log gained
  no record while they ran.
- [x] 3.4 Add the `config` scenario covering both link states: machine ID,
  ROM version, and link config present in each; link state matching the rung.
- [x] 3.5 Add the link-recovery scenario: boot linked → stop server →
  wire command fails honestly → restart server → `bind` → wire command
  succeeds; assert no second banner on the console and two ok HELLO records
  in the log.
- [x] 3.6 Run the full harness ten times consecutively green
  (`python3 harness/run_m0.py --runs 10`) and update the README proof
  section with the M2 scenarios.
