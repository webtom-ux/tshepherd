# Project agent memory

TShepherd is a Python-standard-library terminal application. Start with `README.md`
for launch/configuration and `docs/design.md` for the ownership and state contracts.

- `make check` runs the fleet-independent tests; never substitute a mock focus
  assertion for the opt-in real `tests/herdr-lab.sh` verification.
- All live Herdr test commands and lifecycle operations must use Firstmate's named
  non-default lab helper. Never target a live default fleet in tests.
- Keep native activity independent of task outcome; worker inventory comes only
  from the explicit home's structured Firstmate snapshot. `docs/design.md` owns
  the separate primary-chat identity contract. No namespace scans or raw-log parsing.
- `docs/verification.md` owns verified Herdr identity semantics (explicit default
  uses null session fields; IDs are uppercase Base32) and macOS PTY sharp edges:
  PENDIN is transient kernel state; close an owned PTY master before reaping its shell.
- `docs/focus-latency.md` owns the narrow Firstmate target-metadata proof and
  real-client timing contract; `tests/herdr-lab.sh --latency` verifies Enter during
  a held refresh without replacing visible evidence with CLI success.
- `tests/capture_view.py` captures the actual curses window for opt-in read-only
  visual evidence. It does not dispatch focus; do not replace live evidence with mocks.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
