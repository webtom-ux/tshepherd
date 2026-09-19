# TShepherd

A local terminal dashboard for [Firstmate](https://github.com/kunchenguid/firstmate),
running inside a Herdr tab. TShepherd requires an existing Firstmate installation.
See workers grouped by project, their live activity, task status, and latest update.
Select a worker or Firstmate itself and press **Enter** to switch to its tab.
TShepherd does not create or manage tasks.

![Current TShepherd dashboard with the Firstmate row, provider quota bars, compact model and time columns, and five synthetic workers in Atlas and Harbor](docs/images/tshepherd-preview.png)

*Current interface shown with illustrative, fully synthetic sample data — no real workers or private fleet data.*

## Requirements

- **macOS or Linux** for the full experience, including switching to Firstmate itself.
- **Python 3.9+ with curses** and **Git**. No additional Python packages needed.
- An existing [Firstmate](https://github.com/kunchenguid/firstmate) installation with its fleet snapshot command
  (`fm-fleet-snapshot.v1`) and dependencies, including **Bash** and **jq**.
- A running **Herdr** session with a matching `herdr` CLI on your `PATH`.
  Verified with Herdr **0.9.0 / protocol 22**.
- Optional: a local [`quota-axi`](https://www.npmjs.com/package/quota-axi) CLI on
  your `PATH` for provider quota bars. The rest of the dashboard remains available
  when quota evidence cannot be read.

## Install and run

Clone the source:

```sh
git clone https://github.com/webtom-ux/tshepherd.git "$HOME/TShepherd"
```

Run inside a Herdr terminal tab, replacing the two example paths:

```sh
python3 "$HOME/TShepherd/tshepherd.py" \
  --fm-home "/path/to/firstmate-home" \
  --firstmate-root "/path/to/firstmate-code"
```

`--fm-home` points to your Firstmate data directory; `--firstmate-root` points to
its source checkout. They may be the same directory. Both must be supplied.
If the Herdr CLI is not on your `PATH`, add `--herdr "/path/to/herdr"`.

## Launch with just `TShepherd`

Add this function to `~/.zshrc`. Adjust the script path if you cloned elsewhere,
and replace both Firstmate paths with your own:

```sh
TShepherd() {
  python3 "$HOME/TShepherd/tshepherd.py" \
    --fm-home "/path/to/firstmate-home" \
    --firstmate-root "/path/to/firstmate-code" "$@"
}
```

Reload your shell configuration, then launch from any directory in a Herdr tab:

```sh
source ~/.zshrc
TShepherd
```

For Bash, put the same function in `~/.bashrc` and reload it with `source ~/.bashrc`.

The interface defaults to English. The function forwards options to TShepherd:

```sh
TShepherd --lang de  # German
TShepherd --lang en  # English (default)
```

Only interface labels are translated; project names, task text and source status
values are kept as reported.

Below `Live · local`, the header shows quota bars with whole-number percentages
only for providers that `quota-axi` reports as fresh and usable.
Each bar uses `effectivePercentRemaining` from the provider's primary
`all_models` or `all_products` scope. Independent code-review, model, and product
scopes are excluded; a missing, ambiguous, or unknown primary scope hides the bar.
Bars and provider names shorten below 100 columns, with initials in the smallest
layout. `—` means no displayable quota evidence.
TShepherd invokes `quota-axi` locally with credential refresh disabled, caches
reads for 90 seconds, and hides observations older than 120 seconds. Failed reads
clear the quota display; results reported as stale are excluded. It never starts
login, burn, reset, or routing actions. Use `--quota-axi PATH` when the CLI is not
on `PATH`.

Use **↑/↓** or **j/k** to select, **Enter** to switch tabs, **R** to refresh,
and **q** or **Ctrl+C** to quit. The compact model column shows the confirmed
runtime model and thinking effort (`Sol·M` means Sol with medium effort). Known
Astra, Terra, Sol, Luna, Grok, and Claude names use fixed labels, in that priority
order when several match. Other non-empty runtime model IDs get a label of at
most six characters derived from their model-ID component; no manual mapping
is needed. `?` marks an empty or unconfirmed model, or missing or unrecognized
thinking effort. Which Pi session file counts as unique is defined in the
[design document](docs/design.md#implementation); ambiguous sessions and other
harnesses remain unknown. The wide table has one
**Time** column for the current task; narrow rows show that compact duration
in their detail line. Selecting a worker shows both **Session** and **Task** time
in the footer, while selecting Firstmate shows only its session time. Durations
round down to whole `s`/`m`/`h`/`d`; live durations show `—` when their evidence
is missing or stale.
Task time is elapsed wall time, including waiting or paused time, rather than
active work time. When a task becomes completed or failed, its last confirmed
duration freezes in the row. New work shows its elapsed time once its start is
confirmed; until then, its task time is `—`.
If TShepherd did not observe a trustworthy active interval first, or the current
status is unknown, task time remains `—`. Restarting TShepherd loses retained
durations. Session time can continue independently of task completion.
The [design document](docs/design.md#implementation)
defines the start and end evidence requirements.
Native `done` means ready for input with an unseen response and stays distinct
from `idle`. The unseen-response detail appears in wide worker rows and in the
footer when that worker is selected, subject to the available terminal width.
Live activity and task completion are separate; `unknown` means the current live
state could not be confirmed.
