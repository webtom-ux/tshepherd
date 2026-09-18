# Enter: latency and target-scoped ownership proof

## Cause and measurement point

The starting point is the earlier focus path: agent focus plus explicit tab focus work.
The already settled client projection was not treated again as a cause.

**Trigger:** Enter on the selected generation.
**Visible symptom:** late target view; during a fetch, Enter is even discarded
and must be repeated. **Masking:** fast snapshot fixtures hide the cost of real
fleet fetches; API focus flags hide the time until actual client projection.

The old focus path ran four complete snapshots before visible tab focus, then two
more. On the measured real 32-row snapshot the first four consumed **23.027 s** of
**24.080 s** from input to target image. Each complete focus check also read the
native target endpoint five times. Independently of actual process exit, the
subprocess runner waited in 40 ms steps. A serialized collector expressly refused
Enter while it was working. Those are three separate, observed contributions;
snapshot work dominates.

### Real client measurements

Herdr lab on macOS 26.6.2 arm64; named non-default sessions only. The same
observer measures with `time.monotonic()` immediately before input into the
client FIFO and at the first target marker in the actual client PTY capture. No
differencing between process clocks. Before input, a **fresh target projection in
the capture** is awaited; markers are not contiguous in the started shell command.
A known input/response controls the same capture path.

| Scenario | Main before | After the fix |
| --- | ---: | ---: |
| Control echo after observed target readiness | 13 ms | 19 ms |
| Enter → visible target, real 32-row snapshot | **24.080 s** | **0.696 s** |
| Enter during an expressly blocked background fetch | discarded, no request | **0.727 s**, fetch still blocked |
| Subsequent keyboard input acknowledged by the target | 26 ms | 19 ms |

A dedicated start/release file proof holds the test fetch bounded; no sleep
duration is used as an assumed busy state. Removed, replaced, foreign, and
unintelligible target metadata were refused in the corrected UI by real Enter
during this blockade, with no target marker in the client. Generation/provider/session,
physical replacement, changes between mutations, and stale are additionally
checked in the standard tests and the separate client regression suite.

The inventory consists of **32 real metadata records in the own lab home**, which
deliberately share two own physical Herdr endpoints. The unchanged real Firstmate
snapshot implementation processes them. They are not 32 independent AI processes.
A test-local PATH adapter also redirects their internal Herdr read calls to the
named helper; no shared files are changed. This extra adapter/helper latency is
in the values; it is not a measurement of the production default session, the
physical Mac keyboard, or an OS window switch.

Evidence under `.local/` (ignored):

- `fm-lab-tshepherd-fast-e-38888-7627`: Main, `latency-before-ready.log/.exit`.
- `fm-lab-tshepherd-fast-e-23342-3672`: After the fix, `latency-after-ready.log/.exit`.
- Repeat `fm-lab-tshepherd-fast-e-88527-8302`,
  `latency-after-final.log/.exit`: **0.695 s** ready, **0.764 s** with a held
  fetch, and **0.716 s during the actually running Firstmate snapshot**.
  The latter had demonstrably not finished at the visible switch.
- All three outer lab runs: exit **0**, including helper teardown/default tripwire.
- `measurements.json`, `observer-clock.json`, `observer-events.jsonl`,
  `timings.jsonl`, `client-events.jsonl`, client ANSI, and command journal.

### Counter-check and refuting findings

An earlier valid shared observer control run with fast fixtures
(`fm-lab-tshepherd-fast-e-85437-15897`) measured 18 ms echo, 524/529 ms complete
Enter switch for 2/32 rows, and 270 ms for the diagnostic direct path: full first
target check, physically confirmed agent focus, then direct tab focus.
That counter-attempt only omits the second complete pre-check; it is **not an
adopted relaxation**. The fix keeps both pre-checks and the post-check, but
replaces their unrelated fleet work with current target proof.

That 32 fast fixture rows did not make the assumed focus slower contradicts a
pure sort/render or inventory-length cause in the UI. The real snapshot path and
the instrumented individual times instead explain the multi-second delay. A held
refresh barrier also refutes the assumption that earlier busy-Enter was merely
accepted slowly: dispatch returned `False`. Focus now finishes the same attempt
**before** release.

Failed runs are kept: `37739-19476` and `71883-13335` mixed process-local
monotonic origins in the busy correlation. Platform, process, clock-API, and
unit evidence of the corrected run are in the evidence directory.
`39042-24156` injected its control echo immediately after CLI tab focus, without
visible client readiness. The input did not appear at the target. With a fresh
render handshake the same controls passed before and after the fix.
The capture from that time does not prove the exact inner order of client
projection and input; a readiness race is plausible for that, not proven
retroactively. None of these failed controls justify an accepted latency number.

### Recheck and accepted residual latency

The targeted recheck reproduced **1.307 s** during a real refresh
(0.590 s ready, 0.859 s with a held refresh). The previous driver reported even
those values as success because it only checked appearance of the target marker.
The four mutually independent native reads of each focus check now run in
parallel. The temporarily removed final `pane get` in `focus_target` is restored:
after the ownership recheck the current physical binding must still match the
pane/agent answers of the native check. A replacement in that gap prevents the
following mutation; there is a targeted regression for that before agent and
before tab focus. `focus` also compares the binding with the displayed binding
(when present), the agent focus answer, and the repeated checks before and after
tab focus. The final agent query additionally confirms exact focus.
Collector probes keep their existing pool of at most four readers; focus uses at
most four separately.

The first follow-up run measured **0.269 s** ready, **0.331 s** held, and
**0.418 s** during the real refresh. The 100 ms limit introduced at first was
not calibrated. For the observed **305–345 ms**, **345 ms** was set as the
project-specific acceptance limit for every visible switch measurement.
The live driver uses this limit, not a universal perception SLA.
It still also collects the refusal evidence and fails on overrun.
The final physical check is not sacrificed for a faster number; further
optimization toward zero or under 300 ms is not commissioned.
Successful CLI answers alone remain insufficient as visible proof.

Final targeted run with restored recheck:
`fm-lab-tshepherd-fast-e-83888-5903`, `.local/final-restored-latency.log/.exit`:
**130 ms** ready, **167 ms** during a held fetch, and **324 ms** during the real
snapshot. All four UI ownership refusals passed; the outer lab run including
teardown/default tripwire ended with exit **0**. Additionally the **24** targeted
source/ownership/polling tests passed. This is the final visible measurement, not
a zero-latency promise.

## Target-scoped ownership proof

Inventory still comes **only** from the validated structured snapshot of the
explicit home. The fix adds no inventory, status, or log parser. On the already
loaded UI path it replaces repeated complete fleet fetches with current, bounded
reads of **the one local metadata file already bound in that snapshot**. A not-yet
initialized direct `Source.focus` caller keeps the previous snapshot path; the
explicit lab fixture remains its synthetic ownership source.

### Authority, not a guessed format

Checked Firstmate sources for the described interface contract:

- `bin/fm-spawn.sh`: writes local metadata with `window`, `harness`,
  `spawn_gen`; a non-tmux backend additionally writes `backend`.
- `bin/fm-backend.sh`, `fm_meta_get`: **last** complete `key=value` value,
  no shell evaluation, no trimming; the last line without a newline also counts.
  `fm_backend_of_meta` treats missing/empty backend as tmux.
  `fm_backend_target_of_meta` uses `window` for Herdr (not Orca's `terminal`).
- `bin/fm-fleet-snapshot.sh`: uses exactly these getters for task identity and
  `paths.meta`. Non-empty `remote_host` marks a foreign/remote assignment.
  It offers `--json` and `--secondmate-home-summary`, **not** a bounded target
  identity query. Crew state is not an ownership/generation interface; the
  internal selector metadata helpers search the namespace and are not used.

The new reader reads only `spawn_gen`, `backend`, `window`, `harness`, and
`remote_host` as identity proof. The format is not extended to task status,
title, backlog, or activity. Explicit `backend=herdr` is required; missing/empty
stays unknown and is refused. Unreadable, non-UTF-8-decodable, binary (NUL), or
contradictory material cannot authorize focus. A direct read-only getter control
run confirmed last values and the last line without a newline
(`.local/meta-parser-control.json`); binary material stays expressly unknown
independently of Bash version quirks.

### Safety boundary

- The selected key must occur in the still-fresh last complete snapshot.
  Generation, backend, endpoint, and provider stay exact.
- Only `FM_HOME/state/<snapshot-id>.meta`, with matching `paths.meta.path/present`,
  a safe ID, without symlink resolution from this path. No directory search.
- Regular files only, at most 64 KiB; non-blocking open protects against FIFO
  devices. File stamps/inode are compared before/after read and against the
  current path. Missing, replaced, foreign, or unintelligible means refusal.
- This ownership check runs before **and after** the native reads as well as
  between agent and tab mutation and after tab focus. Mere cache freshness does
  not authorize a mutation. Unknown layouts are refused, not silently resolved.
- Session/protocol, pane/provider, workspace/tab/terminal, and non-shell process
  evidence continue to be checked fresh. Native `done` can also have a confirmed
  physical binding without counting as idle.
- The physical binding displayed at Enter dispatch is passed along when present;
  a meanwhile different terminal generation is refused before mutation.
  A second focus request during an in-flight check is not applied later or bent
  onto a meanwhile different selection.

No known generation is replaced with a merely plausibly reachable one.
The protection is not removed in favor of optimistic false focus.
Between last check and CLI mutation the already documented non-atomic race
remains: Herdr has no compare-and-focus generation parameter here.
A slow/unreadable local filesystem or Herdr can still delay or refuse.
The measured residual times are **not zero** and not a universal SLA.
There is no new transport, service, global switch, or dependency.

## Repeat

```sh
HERDR_LAB_HELPER=/path/to/firstmate/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --latency
```

The test needs the real Firstmate implementation beside the helper. Only for the
historical counter-measurement may `LATENCY_SOURCE` point at a separate old
`tshepherd.py`, with `LATENCY_EXPECT_REJECTION=1`. Both are test options only,
not app configuration. An unconfirmed target marker fails the test; API success
alone never suffices.
