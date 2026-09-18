# Status rediscovery: bounded cause check

## Finding and limit

Reported symptom: longer `unknown`, supposedly only resolvable by restarting the
dashboard. The concrete affected endpoint and its then-authoritative
snapshot/Herdr answers are not available. The production fleet was not queried
or changed; a real user case is therefore **not reproduced**.

Hypothesis: TShepherd permanently holds a stale assignment.
Counter-evidence: `Source.collect` already calls `snapshot`, `primary`, and
`probe` again on every poll, with no cache fallback. Restart and normal polling
use the same construction. History (d02c957, e5509e0) confirms this split:
`Source.current` is a focus/freshness proof, not a discovery cache.

`tests/test_rediscovery.py` runs the real `Source.snapshot` through a local
snapshot subprocess (the snapshot method is not replaced). Native answers are
controlled test data, not live Herdr proof:

- Trigger: shell-only process evidence; visible result: unknown with a reason.
- Condition: with an unchanged snapshot, non-shell evidence arrives again.
  The next normal `collect` yields idle, without a restart; a new Source yields
  the same physical identity. That refutes the claimed local mapping cache for
  this path.
- Changing the authoritative snapshot file to another endpoint rebinds already
  on the next fetch. Invalid endpoints stay unknown.
- Concrete safety hole: with the same logical identity a new physical binding
  could take over the existing selection. `View` now keeps the confirmed physical
  selection across measurement failures and requires reselection on change;
  Enter during a measurement failure also keeps this guard.

No broader investigation without the concrete failing source evidence.
No claim that R repairs a stale *authoritative* Firstmate assignment.

## Implementation

R wakes only the existing collector. After 30 s of unknown the UI requests the
same fetch, with a global 60 s cooldown and monotonic time. In-flight and
already requested fetches are coalesced; there is no parallel second discovery,
new configuration, or extra service. Normal polling stays unchanged and can
resolve unknown before the threshold. Single-flight focus still runs separately
and does not read a fleet snapshot on Enter.

Primary colors still use the worker palette; text and `>` remain visible.
Native done states are not interpreted as work. Unreadable CLI sources get a
brief access hint instead of unfiltered stderr in native rows.

## Verification

`make check`: source reload, unknown→known without restart, comparison with a new
Source, real snapshot endpoint change, invalid targets, physical rebind across
unknown, threshold/cooldown/recovery, manual R key, single-flight collector,
primary palette wide/narrow. Existing focus-hotpath, ownership, generation, and
real PTY tests remain part of the run. This does not replace opt-in live-client
focus acceptance; this change claims no new focus-latency measurement.
