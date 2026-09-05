# Launch kit

Ready-to-publish material for the Claude Window Starter launch. Do not announce a binary download until a complete installation package is published. Check each community's self-promotion rules, add genuine screenshots, and update the installation status before posting. These drafts have not been posted. Do not claim adoption numbers, endorsements, or guaranteed quota gains.

## FINAL RECOMMENDED GITHUB ABOUT

```
macOS app that pre-starts and schedules Claude Code's 5-hour usage window around your work hours, with live 5h and weekly reset tracking.
```

This is the final recommendation: it leads with the platform, states the exact user problem (pre-start/schedule the 5-hour window), names the beneficiary behavior (work-hours alignment), and ends with the supporting capability (live reset tracking).

Alternatives:

- `Claude Code 5-hour window starter and scheduler for macOS — early anchor requests, observed-reset replanning, 5h/weekly quota and Telegram control.`
- `Plan Claude Code usage around your workday: macOS menu-bar scheduler with early warmup requests, 5-hour reset tracking and weekly usage.`

Apply manually (GitHub UI: main page → About ⚙) or via CLI:

```bash
gh repo edit aetsr/claude-code-window-starter --description "macOS app that pre-starts and schedules Claude Code's 5-hour usage window around your work hours, with live 5h and weekly reset tracking."
```

## GitHub Topics (final ordered list)

Apply in this priority order (GitHub may display them differently):

`claude-code`, `claude-code-scheduler`, `5-hour-window`, `usage-window`, `macos-app`, `macos-menubar`, `claude-warmup`, `scheduler`, `telegram-bot`, `usage-tracker`, `swiftui`, `python`, `launchd`, `anthropic`, `claude-code-tools`

15 topics. `claude-code-scheduler`, `5-hour-window`, and `claude-warmup` target the primary search intents. Avoid `rate-limit` because it attracts API throttling queries. Topics categorize the project; they do not guarantee ranking.

```bash
gh repo edit aetsr/claude-code-window-starter --add-topic claude-code --add-topic claude-code-scheduler --add-topic 5-hour-window --add-topic usage-window --add-topic macos-app --add-topic macos-menubar --add-topic claude-warmup --add-topic scheduler --add-topic telegram-bot --add-topic usage-tracker --add-topic swiftui --add-topic python --add-topic launchd --add-topic anthropic --add-topic claude-code-tools
```

## Repository name

**Recommendation: RENAME to `claude-code-window-starter`.**

GitHub renames preserve redirects for code, issues, and clones, and with zero stars and no releases yet there are almost no backlinks to break. The gain is semantic: the repository name itself then matches the exact entity users search for ("Claude Code"), removing ambiguity with Claude chat/API tools in GitHub, Google, and Bing results. Keep the product brand, package name, bundle IDs, and installed paths as **Claude Window Starter** — only the repo slug changes. Do it before launch, then update absolute URLs in `llms.txt`, badges, and this file.

## Awesome-list entry

```markdown
[Claude Window Starter](https://github.com/aetsr/claude-code-window-starter) — macOS app that pre-starts and schedules Claude Code's 5-hour usage window around work hours, with 5h/weekly quota and reset tracking.
```

## Reddit post titles (r/ClaudeCode)

1. I got tired of Claude Code resets landing at useless times, so I built a scheduler
2. I built a macOS app that pre-starts Claude Code's 5-hour window around my work schedule
3. A Claude Code window starter that plans early requests around work hours
4. My Claude Code warmup script grew into a work-hours scheduler with weekly usage tracking
5. An open-source macOS scheduler for Claude Code's 5-hour window, with Telegram control

## Reddit post body (r/ClaudeCode)

I kept hitting the same annoyance: my first Claude Code request at 09:00 meant the next 5-hour reset landed right in the middle of my morning. So I built something to stop thinking about it — Claude Window Starter, open source (Apache 2.0), macOS.

You set your work hours (mine: 08:00–17:00 weekdays). It schedules a tiny tool-free Haiku request ("Reply with exactly OK") a few hours before work — 05:00 by default — which can open a fresh 5-hour window when none is active. Then it checks the actual usage/reset the server reports and replans the rest of the day from that, skipping redundant requests so it doesn't burn quota. There's a menu-bar UI showing 5h + weekly usage, reset countdowns, and the next planned action. Telegram control is optional.

Concrete example: anchors at 05:00 / 10:03 / 15:06. If the 05:00 anchor opens a window, the ~10:00 observed reset becomes the new plan basis and the 10:03 anchor is skipped automatically.

What it doesn't do: no quota increase, no limit bypass, no server-side reset — every anchor is normal subscription usage, Anthropic decides window boundaries, and an active window can't be moved. If usage can't be read, timing is estimated and it says so.

Why not cron? A cron one-liner was my starting point. I wanted observed-reset replanning, sleep/offline expiry instead of backlog firing, quota visibility, and a UI in one place. The Mac must be awake and online at anchor times — this is not a wake alarm or cloud service.

Current setup is a source install on macOS. Downloadable packaging is still being prepared. Feedback on real reset observations and sleep/wake behavior would be helpful.

GitHub: https://github.com/aetsr/claude-code-window-starter

## r/ClaudeAI variant

Title: `I built a scheduler that starts Claude's 5-hour usage window before my workday so resets land at better times`

Body: same structure as above, but frame it for general Claude users — open with "If you use Claude Code (the CLI/agent, not chat) on a subscription, you know the 5-hour usage window…", keep the concrete example and limitations, and link the repo. Only post if the subreddit's rules permit tool posts.

## Hacker News titles

1. Show HN: A Claude Code 5-hour window scheduler for macOS
2. Show HN: Schedule Claude Code warmup requests around work hours
3. Show HN: Claude Code window starter with reset and weekly usage tracking

## Show HN post/comment

I built Claude Window Starter (open source, Apache 2.0) because Claude Code's 5-hour usage reset kept landing mid-morning: my first request at 09:00 meant the next window reset right during focused work.

It's a macOS menu-bar app + Python backend. You configure work hours; it sends a minimal tool-free Haiku request a few hours before work to open a fresh window when none is active, then replans the day from the server-observed reset (skipping redundant requests). It also surfaces 5h/weekly percentages and countdowns, handles sleep/offline gaps by expiring stale actions, and has optional Telegram control.

Technical notes: usage reads go cache → OAuth usage endpoint (existing Claude Code credential) → CLI `/usage` PTY fallback. No API key, no quota bypass, every request is normal subscription usage. Current install is from source (Python 3.10+, Swift 6); no signed binary yet. Happy to answer questions about the scheduling model and the usage-parsing edge cases.

https://github.com/aetsr/claude-code-window-starter

## X / Twitter posts

1. I built a macOS scheduler for Claude Code's 5-hour window: early requests around work hours, reset tracking, weekly usage and optional Telegram control. Uses normal quota; no limit bypass. Source install today. https://github.com/aetsr/claude-code-window-starter
2. Claude Code's 5h reset kept landing mid-morning, so I automated my first request: open-source macOS app, work-hours-aware anchors, observed-reset replanning, menu-bar UI. What it can't do: move active windows or add quota. https://github.com/aetsr/claude-code-window-starter

## Before posting

Check the community's self-promotion rules, add genuine screenshots, and update the installation status. These drafts have not been posted. Do not claim adoption numbers, endorsements, or guaranteed quota gains.
