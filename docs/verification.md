# Verification

## Automated

`make check` runs the unit/integration suite and Python compilation. CI repeats
this on macOS and Linux. No test in the standard suite touches real Firstmate
data or Herdr sessions.

Real PTYs check resize, navigation, and exit during a slow fetch.
After q and SIGINT, echo, canonical line input, cursor normalization, and
alternate-screen exit are verified. A real interactive `/bin/sh` starts the
TUI with synthetic test data, exits it with q or a terminal-generated Ctrl+C,
then runs a command and afterwards interrupts a new `sleep` with Ctrl+C.

The opt-in driver [`tests/status_ui.py`](../tests/status_ui.py) adds captures of
the real curses UI in an isolated PTY for native `done`, `idle`, invalid
provider evidence, and stale task data at `done`. Invocation and source boundary
are in the module docstring: the answers are synthetic, not proof of real Herdr
state changes. The driver is not part of `make check`.

## macOS terminal diagnosis

The first restoration test compared every termios bit immediately after the
application ended. That was the wrong moment for `PENDIN` on the macOS under
test. `termios(4)` and `sys/termios.h` document it as “retype pending input (state)”.

The minimal control without application, curses, subprocess, or resize shows:

1. Fresh PTY: local flags `0x5cb`.
2. Turn `ICANON`/`ECHO` off and restore the original attributes:
   flags `0x200005cb`, even without pending text.
3. Another `tcsetattr` does not change that.
4. After reading a canonical line, **all** attributes match exactly again.
5. `tcsetattr` alone without a canonical transition does not produce this difference.

The trigger is the transition to canonical input; the comparison moment hides or
shows the transient kernel state. There was no reproduced user-visible input
defect. The regression does not mask bits: it first checks echo/canonical/signals,
actual blocking until end of line, and the received text; then it requires full
attribute equality. The ineffective extra restore attempt in application code
was removed.

An independent shell-test hang cause was in cleanup, not in TShepherd:
after a successful shell test, `waitpid` waited for the killed own shell before
its PTY master was closed. The shell stayed in macOS process status `?Es`
(exit path). In the focused control, **only closing that still-open master FD**
let the same PID reap immediately. The smaller shell test without preceding
app/job-control interaction did not show the hang; capture or test order alone
were not a sufficient explanation.

Cleanup now closes its own master before the bounded `WNOHANG` reap.
The full suite and five repeats of the real shell scenario in capture mode
then ran successfully. All signals and waits concern only processes started by
this test, not foreign groups.

## Isolated Herdr live test

Checked on macOS with Herdr **0.9.0, protocol 22**, via
`tests/herdr-lab.sh` and Firstmate's official lab helper:

- Generated non-default session, attached real foreground viewer.
- Synthetic Pi registration over a sleeping Python process; native
  `idle`, `working`, and `blocked` were actually measured through Herdr.
- Task `done` at the same time as native `idle`.
- `Source.focus` and then Enter in the **curses application actually running in
  the Herdr pane** confirmed the expected worker pane on the server.
  That original test alone did not prove a visible client switch.
- Open/refresh alone did not change focus.
- Ctrl+C ended the TUI; the pane foreground returned to the shell.
- Guarded teardown succeeded, unchanged default session according to the helper tripwire.

The real answer to `agent focus` has `result.type = agent_info`, not a dedicated
`agent_focused` type. The application checks the returned physical IDs, provider,
and `focused = true`.

**Limits:** These registrations are not real AI agents and do not prove semantic
busy detection of a model. Other Herdr versions were not live-tested for this
application. The lab proves real focus/terminal integration, not merely mock
dispatch. No production session was focused, paused, restarted, or reconfigured.
Verbose local lab output defaults to `.local/<lab-session>/` on retest (ignored).
`HERDR_LAB_EVIDENCE_DIR` replaces the `.local` base directory; under it the test
creates its session directory with snapshot fixture, focus response, and TUI
captures, including ANSI captures of the filled and stale view.

The focus regression in `tests/herdr_lab.py` lets an unfocused worker change from
`working` to native `done` and confirms exact focus only through Enter in the TUI,
with no prior focus acknowledgement outside the application.
`native-done-before-enter.json` and `native-done-after-enter.json` keep the
answers before and after Enter. The independent task axis is additionally checked
by `test_focus_verified_native_done_without_semantic_completion` in the standard suite.

The separate slow-fetch variant is started with the same isolated helper:

```sh
HERDR_LAB_HELPER=/path/to/firstmate-code/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --slow-fetch
```

It runs `tests/herdr_slow.py` instead of the focus/state scenario: navigation,
real resize via split/zoom, and exit with q or Ctrl+C during a blocked fetch,
then canonical shell input, echo, exact terminal attributes, and SIGINT for a
new shell command. Its files live under `q/` and `ctrl-c/` in the session
evidence directory. The existence of this test does not replace a successful
live run.


## Visible Enter switch in the real client

`tests/herdr-lab.sh --client` additionally checks the previously missing
measurement: dashboard and two synthetic workers sit in separate workspaces/tabs.
Down arrow and Enter are written into the PTY of the real Herdr client, not via
`pane send-keys`. The target process must show its unique screen marker in the
actual client output and acknowledge subsequent client keyboard input with a
second marker. The chosen target first switches natively from working to done;
the regression is therefore retained.

A test-local PATH adapter adds capture and an input FIFO only for the helper
viewer's discarding PTY drain. The original viewer implementation still owns
PTY, process identity, and cleanup; no shared helper file is changed. All Herdr
and lifecycle calls go through the generated named lab helper, with EXIT teardown
and default tripwire. FIFO access is non-blocking; processes are time-bounded.

Removed, replaced, foreign, and stale selections are refused through `Source.focus`
while the same real client shows the dashboard. After each refusal, real arrow
input proves movement of the rendered selection mark in the dashboard view; no
worker marker may appear. These negative cases inject the invalid selection
directly at the focus interface (not through UI Enter) so the original generation
can be checked exactly even after removal. Unit tests additionally cover changes
between agent and tab mutation and partial failures.

The successful run on Herdr 0.9.0 showed target content and subsequent input in
the client PTY plus all four unchanged negative views; both live variants ended
helper teardown without tripwire errors. `positive-client.ansi`, `*-client.ansi`,
`native-done-before.json`, and `commands.jsonl` live in the local session evidence
directory. This is not a recording of a physical Mac keyboard or OS window
activation. Multiple attached clients were not tested; Herdr's public tab focus
projects session-wide, not guaranteed into exactly one OS window. An API focus
flag or a directly read pane buffer alone is still expressly insufficient as
proof of the visible switch.

## Enter latency and in-flight background fetch

The `tests/herdr-lab.sh --latency` variant, its measurement contract, previous
results, and the still-open latency acceptance are documented in
[Focus latency](focus-latency.md).

## Real session form and template-like view

The first named lab session hid two integration errors: early lab IDs contained
only digits, while the real fleet already used `wA:p2`; and named sessions return
their name, but the reserved default session returns `null`. The real preview
therefore showed seven unknown live states.

Herdr **v0.9.0** is the checked authority here:

- [`src/session.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/session.rs):
  `normalize_name("default")` yields `None`; explicit `--session` takes precedence
  over inherited socket/session context.
- [`src/cli/status.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/cli/status.rs):
  client and server serialize this optional session name. Default `null` is a
  present value, not a missing field.
- [`src/workspace.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/workspace.rs):
  public IDs use the readable Base32 alphabet whose tenth value is `A`.
  Uppercase is regular; handles are not guessed from ordering.
- [Socket documentation](https://herdr.dev/docs/socket-api/): default socket in
  the configuration directory, named sockets under `sessions/<name>/herdr.sock`.

The fix does not accept arbitrary `null`: an explicit default target, present
matching client/server fields, a running compatible server, and a consistent
socket namespace are required. Provider/pane/physical ID checks before focus
remain. Missing, foreign, contradictory, and stale evidence stays unknown.

The read-only counter-check against exactly the snapshot's own real endpoints
yielded **six idle and one working** instead of seven unknown. No real worker was
focused or controlled for this proof. The isolated lab now deliberately exceeds
the early digit IDs and checked real focus on **`wA:p1`**, including
removal/replacement/foreign/stale refusal and empty inventory. The default
tripwire passed again after teardown.

Earlier formatting also had a concrete defect: final truncation normalized all
spacing and destroyed column alignment. Layout spaces are now kept. Stacked
colored number blocks, colored project headings with counts, indented numbered
single-liners, and fixed columns follow the reference. Live and task remain two
columns for truth reasons; the host sidebar, other brand graphics, and workers
that are not present are not copied.

For the visual comparison the real curses application was run on a **120×40**
PTY with real read-only source data. After a successful fetch, `tests/capture_view.py`
reads text **and attributes from the actually drawn curses window**, not from the
layout function or a mock. The corresponding local PNG proof renders those cells
in the browser at roughly comparable content area to the reference (1590×1120
pixels). It is not a desktop photo: font and palette of the browser test image
can differ from the host terminal. The actual Herdr preview was additionally
captured as visible text and ANSI; only the already released preview tab was
updated.

Opt-in cell capture (no focus actions):

```sh
python3 tests/capture_view.py --fm-home /path/to/home \
  --firstmate-root /path/to/code --output .local/view-120x40.json
```

Compared were header proportions, vertical color blocks, uniform columns, group
indent, blank lines between projects, and the density of worker rows.
The seven actually present workers naturally leave more free space than the
32-worker reference. Narrow/resize/restoration tests remain part of the suite.

## Firstmate owner and fixed first row

On macOS with Herdr **0.9.0 / protocol 22**, and with the same reader contract now
available on Linux, the real home-lock owner is checked read-only: kernel generation before
lock mtime, its own injected Herdr IDs and socket, matching native pane/agent physical
identity, and direct ancestry from the reported pane shell. The real default owner
provided **no `HERDR_SESSION`**, but did provide the canonical default socket. The
candidate came from the lock, not from a recorded pane ID, title, or the dashboard
process. No focus or lifecycle action against the real owner, preview, or worker was
part of this check.

The reproducible opt-in test is:

```sh
HERDR_LAB_HELPER=/path/to/firstmate-code/bin/fm-herdr-lab.sh \
  bash tests/herdr-lab.sh --primary-client
```

`tests/herdr_primary.py` uses a synthetic home, an expressly synthetic harness
argv0/registration, and a Python chat-echo process. The existing Firstmate
classification is actually invoked. Apple's `/usr/bin/python3` launcher overwrites
argv0 on framework exec; the fixture therefore uses the framework binary directly
for its synthetic identity. No real AI harness is started and no model activity
is claimed.

The successful run proves:

- A fixed, standalone Firstmate row above exactly one counted worker; the
  dashboard runs in a **different** tab/workspace from the primary chat.
- Down/up arrow and Enter go through the real Herdr client PTY, not via pane
  injection. Afterwards the unique primary screen marker appears **in the actual
  client output**; further client input is answered by the target process. An API
  focus value alone does not count as this proof.
- Another synthetic home-lock PID with a deliberately copied injected target
  identity fails native shell ancestry.
- A missing, ambiguous/malformed, and generation-stale lock is visibly
  unavailable. Enter again leaves the client view unchanged; the old selection
  is also refused through the direct focus entry.
- After a real guarded stop/re-provision, public pane IDs remain, but terminal ID
  and owner lifetime do not: the old lock is refused.
- Teardown and default-session tripwire passed. Worker-client, classic Herdr, and
  slow-fetch lab were also checked with the extra row.

`tests/test_primary.py` adds fleet-independent tests for stable order,
scroll/narrow display, keyboard reachability, worker counters, no silent
selection replacement, native-done, time/generation/ancestry races, missing and
duplicate identity, default-socket distinction, and missing process visibility.
Mock mutation assertions in it never replace the separate client proof.

`--primary-client` also runs `tests/herdr_narrow.py`: the real TUI runs with the
named lab's live source in its own **28×16** PTY. Three j/k navigation cycles
each check eight consecutive curses frames with a stable selected worker title
and selection mark, its second state line, a visible fixed Firstmate row, and
unchanged worker counters. The narrow line is still truncated at window width.
`narrow-frames.jsonl` captures the actually drawn curses window; `narrow-client.ansi`
contains the PTY recording. This separate terminal capture is not a Herdr client
switch; that is checked by the Enter scenario described above.

This does not claim atomic focus/generation guarantees, actually forced PID recycling,
foreign OS-window activation, or support outside the verified macOS/Linux readers.
The stale-PID tests create the relevant time/generation condition in a controlled way;
the restart check uses a real named server restart. Raw client evidence and selected
owner observations are in the [session evidence directory](#isolated-herdr-live-test).

## Model labels: real PTY UI with a synthetic source

On 2026-09-13 the previously reported missing lab helper was reproduced:
`env -u HERDR_LAB_HELPER bash tests/herdr-lab.sh` ends before provisioning with
`Set HERDR_LAB_HELPER to Firstmate bin/fm-herdr-lab.sh`. That is a missing
live-test prerequisite, not a reproduced product defect. For this model
acceptance a deterministic source in the real PTY UI was expressly released.

Reproducible, targeted check without Herdr calls:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/model_labels_pty.py
```

All **21 cases passed**: seven model cases each at 120×24, 40×24, and 28×24.
`curses.wrapper`, `tui`, Poller, Source, and rendering actually run; `instr`
reads the drawn window cells after `refresh`. j/k/q reach the real input loop
through the PTY master. The check requires both visible model/effort labels
(Firstmate and worker), selection change, the worker counter, and native idle;
at 120 columns also flush model/live columns.

| Acceptance scenario | Observed labels in Firstmate and worker row |
| --- | --- |
| Fixed Grok/Claude names | `Grok·H`, `Claude·M` |
| Existing name takes precedence (`provider/claude-astra-5`) | `Astra·M` |
| Generic, bounded name; embedded grok without a fixed hit | `Gemini·H`, `Long-u·XH`, `Megrok·L` |
| No confirmed runtime selection | `?·?` |
| Wide and narrow view | All seven labels complete at all three widths |

**Evidence limit:** real curses UI and PTY input, **synthetic source**.
The test-local runner supplies fleet, Herdr, and identity-reader answers;
Source checks them with unchanged production guards. Neither real Firstmate/AI
processes nor OS owner detection or Herdr client focus are proven.
No focus is triggered, and no fleet or lifecycle function is invoked.
The two targeted existing tests
`SourceTests.test_probe_collects_exact_session_model_and_effort_only` and
`PrimaryTests.test_primary_without_unique_runtime_session_stays_unknown_model`
also passed. Production guards were not changed for this PTY proof. Cell
captures and ANSI recordings are created temporarily inside the worktree and
removed after the test; a full suite was not run.
