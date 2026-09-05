# Warmup Cron Job vs Claude Window Starter

Target question: "Why not just use a Claude Code warmup cron job?" Short answer: a fixed cron warmup sends one blind request; Claude Window Starter plans a workday of requests and adapts them to the reset times Anthropic's servers actually report. Repository: <https://github.com/aetsr/claude-code-window-starter>.

## What a simple warmup does

A typical warmup is a `cron`/`launchd` one-liner that runs `claude -p "say hi"` at, say, 07:00 every weekday. It may open a fresh 5-hour window when none is active. It costs almost nothing to set up, has no dependencies beyond Claude Code, and is fully transparent. Its limits: fixed time regardless of work hours or server state, no visibility into quota or resets, no protection against redundant requests inside an active window, no handling of sleep/offline backlogs, and credential/hookup management is yours.

## What Claude Window Starter adds

Claude Window Starter is a Claude Code 5-hour window scheduler and starter for macOS. On top of the same "early request" idea it provides work-hours-aware planning (3-hour lead, 303-minute cadence, weekdays, timezone-aware), observed-reset replanning (skip redundant anchors, replan from reported reset + 180s grace), 5-hour and weekly quota visibility with countdowns, duplicate-action locking, missed-action expiry after sleep/offline gaps, a SwiftUI menu-bar interface with background launchd helpers, network monitoring and recovery, existing-credential usage reads (OAuth endpoint → CLI `/usage` fallback, no API key), and optional Telegram status/control.

## Factual comparison

| Dimension | Simple warmup cron | Claude Window Starter |
| --- | --- | --- |
| Schedule | Fixed time you set | Adaptive work-hours plan + previews |
| Server-observed reset | Ignored | Replans from reported reset + grace |
| 5h usage monitoring | None | Percentages, resets, countdowns |
| Weekly usage monitoring | None | Percentages + exhaustion suppression |
| Work-hours planning | Manual | Timezone/weekday/lead/cadence config |
| macOS menu bar | None | SwiftUI app + planner views |
| Telegram control | None | Optional allowlisted bot |
| Sleep/wake recovery | Fires backlog or misses silently | Stale actions expire; power assertions request wakefulness |
| Network recovery | None | Connectivity monitoring; tick on reconnect |
| Credential handling | Your shell setup | Existing Claude Code login; Keychain token for Telegram |
| Background service | cron/launchd entry you maintain | Installed launchd agents |
| Cost | One request per fire, always | Skips redundant/weekly-exhausted fires to save quota |
| Requirements | Claude Code only | macOS 13+, Python 3.10+, Swift 6 build tools, signed-in Claude Code |

## Which should you choose?

Choose a simple warmup if you want one fixed daily ping, minimal moving parts, and you watch quota yourself. Choose Claude Window Starter if you want the schedule to follow shifting work hours, adapt to observed resets, show quota state, survive sleep/offline gaps gracefully, or be controlled remotely via Telegram. Neither option increases quota, moves an active window, or guarantees a reset time — Anthropic decides all of that, and every request consumes normal subscription usage.

See the [5-hour window scheduling guide](CLAUDE-CODE-5-HOUR-WINDOW.md) for anchoring internals and the [FAQ](FAQ.md) for standalone answers.
