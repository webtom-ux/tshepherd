#!/usr/bin/env bash
# Opt-in real Herdr verification. No command ever targets the default fleet.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${HERDR_LAB_HELPER:?Set HERDR_LAB_HELPER to Firstmate bin/fm-herdr-lab.sh}"
HERDR_LAB_SESSION=$("$HERDR_LAB_HELPER" name tshepherd-fast-enter)
export HERDR_LAB_HELPER HERDR_LAB_SESSION
trap 'rc=$?; "$HERDR_LAB_HELPER" teardown "$HERDR_LAB_SESSION" || exit $?; exit "$rc"' EXIT
"$HERDR_LAB_HELPER" provision "$HERDR_LAB_SESSION"
if [[ "${1:-}" != --client && "${1:-}" != --latency && "${1:-}" != --primary-client ]]; then
  "$HERDR_LAB_HELPER" viewer start "$HERDR_LAB_SESSION"
fi
case "${1:-}" in
  '') python3 tests/herdr_lab.py ;;
  --slow-fetch) python3 tests/herdr_slow.py ;;
  --client) python3 tests/herdr_client.py ;;
  --latency) python3 tests/herdr_latency.py ;;
  --primary-client) python3 tests/herdr_primary.py ;;
  *) echo 'Usage: tests/herdr-lab.sh [--slow-fetch|--client|--latency|--primary-client]' >&2; exit 2 ;;
esac
