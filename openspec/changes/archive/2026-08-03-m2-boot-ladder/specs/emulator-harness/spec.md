## ADDED Requirements

### Requirement: Mid-run server control
The harness SHALL be able to stop and restart the server while SIMH is still running, driven by a marker the machine prints on the console, so that link loss and link return can be staged inside a single boot. The restarted server SHALL listen on the same port and write to the same oracle log as the one it replaces, so assertions cover the whole run. Deterministic teardown SHALL still hold: whichever server process is alive at the end of the scenario is terminated, on success and on failure alike.

#### Scenario: Server stopped and restarted inside one boot
- **WHEN** a scenario stops the server after the machine has reached the prompt and restarts it on the same port
- **THEN** SIMH keeps running throughout, and the oracle log holds the records from both server lifetimes in order

#### Scenario: Teardown after a staged restart
- **WHEN** a scenario that restarted the server fails partway through
- **THEN** no server process or bound socket survives the run, and the next run starts cleanly

### Requirement: Boot-ladder inspection scenarios
The harness SHALL include scenarios proving the ladder is inspectable from the prompt: `ls /dev` in both link states and `config` in both link states. Each SHALL assert on the machine's console output via SIMH's matcher — these commands touch no wire, so the oracle log is not the evidence — and SHALL additionally assert that the oracle log records no request for the interval in which they run.

#### Scenario: /dev while linked
- **WHEN** the scenario sends `ls /dev` after a successful HELLO
- **THEN** the console shows the self-test devices and the bound drive letter with its volume name, and the oracle log gained no record

#### Scenario: /dev in local-only mode
- **WHEN** the scenario boots with no server and sends `ls /dev`
- **THEN** the console shows the wire down and no drive letter claiming a live volume

#### Scenario: config in both link states
- **WHEN** the scenario sends `config` with the link up and again on a local-only boot
- **THEN** both runs show the machine ID, ROM version, and link config, and the link state each reports matches the rung the machine is on

### Requirement: Link-recovery scenario
The harness SHALL include a scenario that proves one-command recovery end to end within a single boot: boot with the server up, stop the server, confirm a wire command now fails honestly on the console, restart the server, send `bind`, and confirm the link is back. It SHALL pass only when both proofs hold — the console shows the recovery and a post-`bind` wire command succeeding, and the oracle log shows two ok HELLO records for the machine, the second after the restart.

#### Scenario: The recovery run
- **WHEN** the link-recovery scenario executes
- **THEN** it exits 0, with the honest failure and the successful re-bind both matched on the console, and two ok HELLO records in the oracle log

#### Scenario: Recovery without a reboot
- **WHEN** the machine re-binds after the server returns
- **THEN** the console shows no second boot banner, proving the prompt was never restarted

#### Scenario: Earlier milestones keep passing
- **WHEN** the full harness runs after M2 lands
- **THEN** the spine, run-COM, type-missing, server-down, and unknown-machine scenarios still pass unchanged
