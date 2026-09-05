# Claude Code 5-Hour Usage Window Starter and Scheduler

Claude Window Starter is an open-source macOS app that automatically starts and schedules Claude Code's 5-hour usage window around your working hours. This guide explains the problem it solves, how its window anchoring works, and what it does not do. Repository: <https://github.com/aetsr/claude-code-window-starter>.

## The problem

Claude Code subscriptions include a 5-hour usage window (also called the 5-hour limit, 5h window, usage window, or session window): after your first request, a server-side timer runs for roughly five hours, then usage resets. A separate weekly (7-day) limit bounds longer-horizon use. If your first request happens when you sit down at 09:00, the next reset can land mid-morning and interrupt focused work — and a bare quota tracker only tells you about it afterward.

## What Claude Window Starter does

Claude Window Starter is a Claude Code 5-hour window scheduler and starter. You configure work hours and timezone; it plans lightweight anchor requests ahead of and through your workday, observes the reset times Anthropic's servers actually report, and replans later anchors from those observations. It also displays live 5-hour and weekly quota percentages, reset times, and countdowns in a macOS menu-bar UI, with optional Telegram control.

## Example workflow

A developer works 08:00–17:00 on weekdays. Claude Window Starter plans anchors at 05:00, 10:03, and 15:06 (3-hour lead, 303-minute default cadence, clamped to local midnight). At 05:00 the Mac — awake and online — sends a fixed Haiku request (`Reply with exactly OK. Do not use tools.`). If no window was active, Anthropic may open a fresh 5-hour window; the app's next usage read shows the reported reset (~10:00), and the 10:03 anchor is skipped as redundant and replanned for reset plus a 180-second grace period. If a window was already active at 05:00, the anchor is likewise skipped to save quota. All times are illustrative; Anthropic controls actual windows.

## How window anchoring works

An anchor is a scheduled request intended to begin normal subscription usage — not a server-side reset command. At each due action Claude Window Starter (1) queries usage via cache (≤300s) → OAuth usage endpoint → CLI `/usage` PTY fallback; (2) if an active 5-hour window is observed, skips the request and replans from reported reset + grace; (3) if weekly exhaustion is observed, suppresses the request; (4) otherwise sends the fixed tool-free Haiku anchor through the signed-in Claude Code CLI with locked decisions preventing duplicates. Requests more than ~5 minutes late expire rather than replaying. If measurement fails, an anchor can still run with estimated confidence — success alone does not prove a new server window started.

## Reset tracking

Claude Window Starter treats server data as observations and local math as estimates. OAuth `resets_at` (or parsed `/usage` text) feeds the replanner and the countdowns; manual `/calibrate_5h` adjusts local scheduling only. Reads may reuse a cache up to five minutes old (scheduler snapshots use a 900-second observation cutoff), so instantaneous alignment is not guaranteed and the OAuth endpoint/CLI format can change.

## Work-hours scheduling

Work-hours scheduling is the adaptive core: timezone-aware start/end times, active weekdays, lead-in, cadence, and grace are configurable (`config/config.example.json` defaults: 08:00–17:00, weekdays, 303-minute intervals, 180-second grace). Manual calibration is a fallback for when server data is missing, not a way to move server windows.

## Why starting a window early can be useful

A pre-work anchor shifts when your allowance opens, so the following reset — about five hours later — can fall at a lunch break or mid-afternoon instead of mid-morning. It organizes existing quota around your day; it never creates extra quota, and an already-active window cannot be moved.

## What the project does not do

Claude Window Starter does not increase quota, bypass limits, reset server-side timers, manipulate authentication, run while the Mac sleeps, wake a sleeping Mac, or run in the cloud. Every anchor consumes normal subscription usage. It is not affiliated with Anthropic.

## Difference from a simple warmup cron job

A cron one-liner sends a fixed daily request and stops there. Claude Window Starter adds a full workday plan, observed-reset replanning, 5h/weekly visibility, duplicate-action locks, sleep/offline expiry, a menu-bar UI, network recovery, Keychain-safe credential handling, and Telegram control. Full comparison: [WARMUP-VS-SCHEDULER.md](WARMUP-VS-SCHEDULER.md).

## Installation

Requires macOS 13+, Python 3.10+, Swift 6 toolchain, and signed-in Claude Code (`claude auth login`); no Anthropic API key needed. From a clean checkout:

```bash
git clone https://github.com/aetsr/claude-code-window-starter.git
cd claude-window-starter
claude auth login
./scripts/install-macos.sh
```

Details, quick start, and uninstall: [README](../README.md#installation). Download installer ZIPs from [GitHub Releases](https://github.com/aetsr/claude-code-window-starter/releases/latest).

## GitHub repository

Source, issues, and docs: <https://github.com/aetsr/claude-code-window-starter>. Bug reports with reproducible usage-parsing, reset, or sleep/wake observations (credentials removed) are welcome — see [CONTRIBUTING](../CONTRIBUTING.md).
