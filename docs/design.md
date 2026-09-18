# Requirements and Design

## Goal

TShepherd is a standalone local live terminal overview for your own Firstmate workers.
It runs in a normal Herdr tab on macOS or Linux. The visual reference is the contract
for the terminal content area: compact color blocks with numbers to the left of labels,
spacing between project groups, and indented aligned worker rows. Herdr's sidebar/tab
bar is not recreated; the branding remains TShepherd, without copied marks, images, or
mascots.

The view answers: who is working, who is waiting, who is natively idle, which
task is completed, and where trustworthy information is missing? Task name and
latest known activity help with orientation. An explicit selection with Enter
switches to the matching Herdr view.

## Hard limits

- Firstmate remains the sole task and inventory source; there is no second control plane.
- An explicit home defines the ownership boundary. No scan of shared Herdr
  namespaces, and no automatic recursion into other homes.
- Native agent activity and semantic task status are independent axes.
  Missing, contradictory, stale, or unreachable data must not appear as
  confirmed idle or as a current completion.
- Observation and explicit focus only: no spawn, stop, send, delete,
  scheduler, or other control functions.
- No global install, telemetry, public services, or changes to Firstmate's
  shared scripts and configuration.

## Implementation

A Python standard-library application (`tshepherd.py`) avoids extra frameworks.
`curses.wrapper` owns the terminal lifecycle. Rendering, state projection,
selection, data access, and polling are separate functions/classes and are
testable without a live fleet.

`Source.snapshot` calls the JSON interface of the configured code root with an
explicit home. Schema, home, and unique worker identities are checked.
Only `tasks` metadata determines worker rows. The supported short title/activity
fields are used, never raw logs, report bodies, or transcripts.

`Source.probe` adds a native observation for each exactly bound local Herdr pane.
It checks session/compatibility, pane ID, provider, and workspace/tab/terminal ID.
`default` is normalized to Herdr's bilateral JSON `null` only for a target that is
explicitly routed that way. Missing session fields and contradictory socket
namespaces are rejected. Public pane handles use Herdr's documented uppercase
Base32 alphabet; the physical round-trip check is unchanged.
A shell-only foreground or missing process information is not enough to confirm
stale registrations as live. Native `idle` and `done` are both ready for input;
`done` stays visible as an unseen response, distinct from `idle`. A native report
is still not a semantic statement about running tools; the UI names that limit.
A successful check yields the physical binding independently of the activity
assignment. `Source.focus` requires that binding, not a particular live state;
the input-ready `done` state therefore does not block focus. All subsequent
ownership, freshness, and identity checks remain required.

`Poller` owns a collector and a separate single-flight focus worker.
The supplementary quota display stays independent of snapshot inventory,
activity, and focus authority. The collector reads it after releasing its
busy state and delivers it to `View` as a separate result.
Provider selection, freshness, and display are described in the
[README](../README.md#launch-with-just-tshepherd).
Enter is accepted immediately even during a refresh; a second focus request
during an in-flight focus check is refused, not queued for later.
Within a refresh there are at most four native readers with a shared time
budget. Focus besides that uses only its bounded target-related reads. Subprocesses
have their own groups, are bounded in time and output, and are terminated on
cancel. No extra service and no durable copy of task status are created.
R and bounded unknown retries wake the same collector, without agent control.
Cause check, threshold/cooldown, and limits: [Status rediscovery](status-rediscovery.md).

`View` keeps snapshot, native measurements, quota observations, selection, and
confirmed task intervals in memory. For workers the combination of task ID,
spawn generation, backend, endpoint, and provider applies, not the row number.
On dispatch the displayed physical binding is also passed along when confirmed.
The confirmed physical selection survives measurement failures; a different new
binding requires explicit reselection. Sorting or removal must not silently make
another worker the target. Enter checks the selected target against the last
fully delivered, still-fresh snapshot inventory. The current local ownership
check reads only that worker's exactly bound metadata file;
[contract and authority](focus-latency.md#target-scoped-ownership-proof) limit
fields, size, file type, and path. After the native reads, ownership and
freshness are checked again; then a final `pane get` confirms the same physical
binding once more before the following mutation. Neither an unchanged snapshot
alone nor a merely stored pane handle authorizes focus. The CLI call receives
safe separate arguments with an explicit session. After confirmed agent focus,
`focus_target` rechecks every target-related guard and requires the same
physical identity before that tab is focused explicitly. This second CLI step
projects Herdr's session client views; agent focus alone does not.
Ownership, freshness, physical binding, and exact agent focus are then
confirmed again. Partial failures do not claim complete success; the footer
confirms server state, not a particular OS window. Atomic protection against
changes after this last check is not possible with the API in use.
Firstmate's own selection identity and target check are described in
[Primary chat](#primary-chat).

The view shows fetch age, data errors, inventory gaps, and unknown states.
`rows_for` appends the native `done` explanation to the display reason when
that state is confirmed, without replacing the delivered task activity.
With a fresh snapshot and a valid native measurement but a stale `current_state`,
the task axis stays `unknown`; its freshness hint remains next to the native
explanation. Counters are explicit observation counts; `completed` belongs to
the task axis and overlaps with live states. Colored number blocks sit
vertically beside the branding; project groups have their own colors and
indented single-line workers. Agent, model, live, task, task time, and latest
activity sit on fixed cell columns. For Pi, the model cell reads only a session
file that is unique within the confirmed process generation of the exact
worktree and follows that file's active entry chain.
User-facing meaning of the model/effort labels is described in the
[README](../README.md#launch-with-just-tshepherd); derivation is implemented by
`compact_model` in `tshepherd.py`.
Launch/dispatch metadata is not a substitute for the current selection.
Layout and meaning of the time display are described in the
[README](../README.md#launch-with-just-tshepherd). Both time bases come from the
reconfirmed process generation: for workers the same process must be bound
exactly to task ID, spawn binding, and pane through its selected environment;
for the primary chat the verified lock-owner generation applies.
Snapshot observation times and unconfirmed metadata are not treated as a start
time. `rows_for` releases the task start only for a fresh, confirmed outcome of
`working`, `parked`, `blocked`, or `paused`. `View` remembers, for that
identity-equal worker row, the last confirmed interval from task start to
`Native.observed` of the fresh native measurement. This upper bound is not an
authoritative completion time; time until a later completion report is not
added. For a fresh `done` or `failed` outcome the display uses this interval
even without a current native time measurement. Missing measurements for the
same identity do not delete it. Another confirmed active measurement updates
the interval; a different confirmed task start replaces the previous start.
Removed or changed row identities lose their interval. The regression
`test_terminal_task_duration_survives_missing_native_measurements` in
`tests/test_tshepherd.py` covers measurement loss, a new start, and identity
change. Session start does not depend on outcome. Both starts require a fresh,
identity-equal native measurement, and for workers also a fresh snapshot.
The time values do not affect sorting and are not stored durably.
Source text fields are stripped of control characters; formatting spaces are
kept when truncating.
Below 78 columns, rows are stacked. Unicode widths are taken into account.
Colors are not the only encoding: state words remain readable.

## Primary chat

The fixed `PrimaryRow` sits above the project groups independently of worker
sort order and scroll position. It has no task metadata and no outcome;
all existing counters remain worker-only counters. Native activity stays
independent of focusability here as well: native `done` is ready for input
and visible as an unseen response; with confirmed identity it remains reachable.
Missing or stale evidence is visibly unavailable/unknown, never replaced by
another endpoint.

The current fleet snapshot does not export a primary chat binding.
`primary_identity.py` therefore reads only the PID lock of the explicit home
and the existing Firstmate harness classification from
`bin/fm-session-lock-lib.sh`, without acquiring the lock or writing files.
The bounded OS subprocess keeps the existing macOS reader (`proc_pidinfo(PROC_PIDTBSDINFO)`
for PID generation/ancestry and `sysctl(KERN_PROCARGS2)` for selected Herdr identity
fields) and adds an equivalent Linux `/proc` reader for PID/UID/generation, ancestry,
and the same selected environment fields. OS buffers are evaluated only in memory;
argv and other environment values are never emitted or stored. Unsupported platforms
and restricted process visibility remain explicitly unavailable.

The process generation must have started before the lock mtime; lock inode,
timestamps, content, owner process, and that process's own injected identity are
compared repeatedly. Missing/duplicate identity fields, symlink locks, invalid
PID, and unreadable data refuse the binding. For the default owner Herdr omits
`HERDR_SESSION`: only that owner's canonical default socket allows the explicit
`default` route here; after that the known bilateral JSON-null/socket/compatibility
checks must pass. No dashboard environment variable and no label selects the
candidate.

`Source.primary` joins this candidate with exact native session, pane, agent, and
process information. Pane and agent must supply the same physical
workspace/tab/terminal identity. The lock PID must reach the shell reported by
exactly this pane in at most 24 current parent steps; the generations of the
chain are checked again. That excludes a foreign pane despite a valid
registration, and restored public IDs without the old owner. After the OS check
the physical pane binding is read again.

Selection binds home/lock, PID/start generation, injected endpoint, provider,
and physical IDs. An owner change does not retarget an existing selection.
`Source.primary_target` rechecks only this owner/endpoint; on Enter it does not
issue a fleet snapshot or worker queries. Agent/tab focus use the shared
existing navigation path with repeated target checks before the second mutation
and at the completion confirmation.

The reads are not atomic. Between two measurements or after the last check,
process, lock, or pane can change. Lock mtime is a conservative reuse check,
not a kernel-signed ownership generation; manipulation by the same local user
or a changed system clock is not an extra security boundary. Same-PID exec
still requires the current harness check.
There is no new service, no shared state schema, and no fallback to a name
search or guessed process interpretation.

## Acceptance points

| Area | Evidence |
| --- | --- |
| Mapping, completion/idle split, errors/stale | `tests/test_tshepherd.py` |
| Logical project grouping, counters, selection identity | `tests/test_tshepherd.py` |
| Fixed Firstmate row, own counter boundary, owner/generation/freshness/error cases | `tests/test_primary.py` |
| Primary chat via a real client keyboard; foreign owner and restart | `tests/herdr-lab.sh --primary-client` on macOS |
| Single-flight focus beside a blocked refresh, target metadata, budget, cancel, safe argv | `tests/test_tshepherd.py` |
| Rendering, narrow windows, resize, input during fetch | `tests/test_terminal.py` and rendering tests |
| Echo, canonical, signals, cursor/altscreen, subsequent shell | real PTY tests in `tests/test_terminal.py` |
| Actual Herdr focus, real TUI, and visible client switch in the lab | [Isolated live test and client variant](verification.md#isolated-herdr-live-test) |

A mock confirmation must not be presented as a real Herdr focus confirmation.
The live test uses the named non-default lab helper for every Herdr command,
including provisioning, viewer, and teardown. The default fleet and foreign
projects are not test targets.
