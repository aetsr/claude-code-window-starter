# Launch copy

Use after reviewing the release and screenshot checklist. Do not announce a binary download until a complete installation package is published.

## GitHub About

Ranked options (all comfortably below GitHub's practical 350-character description limit):

1. Schedule Claude Code's 5-hour usage window before work. macOS starter with reset tracking, weekly quota monitoring, adaptive work-hours planning and Telegram control.
2. A Claude Code 5-hour window starter and scheduler for macOS. Send an early request, track usage resets and weekly quota, and adjust scheduling around your workday.
3. Plan Claude Code usage around your workday: a macOS menu bar scheduler with early warmup requests, 5-hour reset tracking, weekly usage and optional Telegram control.

Option 1 is recommended: it leads with the task and timing benefit. Option 2 foregrounds the exact product category. Option 3 is natural but delays the five-hour concept.

## GitHub Topics

Priority order (GitHub may display them in another order):

`claude-code`, `claude-code-usage`, `5-hour-window`, `scheduler`, `usage-limit`, `usage-tracking`, `warmup`, `macos`, `menu-bar`, `claude-code-quota`, `quota`, `automation`, `claude`, `anthropic`, `telegram-bot`

These 15 topics are accurate and within GitHub's limit of 20. `5-hour-window`, `claude-code-quota`, and `claude-usage` are syntactically valid; the first two provide useful specificity, but their search popularity is unverified. `claude-usage` is optional and overlaps `claude-code-usage`. Avoid `rate-limit` here because it can attract API throttling queries. Topics categorize the project; they do not guarantee ranking.

## Repository name

Recommended final name: **claude-code-window-starter**.

The current **claude-window-starter** is short and reasonably descriptive. Adding `code` removes ambiguity with Claude chat/API tools and matches the product users search for. Expect a modest clarity benefit, not a proven ranking boost. A rename costs link, badge, clone URL and documentation maintenance; do it before launch if desired. Preserve package names, bundle IDs and installed paths. Metadata/title improvements remain worthwhile without a rename.

## Reddit post title

1. I built a macOS app to schedule Claude Code's 5-hour usage window before work
2. A Claude Code window starter that plans early requests around work hours
3. Tracking Claude Code resets and scheduling warmup requests from the macOS menu bar
4. My Claude Code warmup script grew into a work-hours scheduler with weekly usage tracking
5. An open-source macOS scheduler for Claude Code's 5-hour window, with Telegram control

## Reddit post body

I wanted to stop thinking about when to send my first Claude Code request so a later reset would fit my workday. I built Claude Code 5-Hour Window Starter for that.

You set your work hours. It plans a small, tool-free Haiku request before work, checks usage when an action is due, and adjusts the remaining plan if it sees a window already running. It also shows five-hour and weekly usage, reset information, and the next planned action. Telegram control is optional.

It does not increase quota, bypass limits, or reset anything server-side. Requests consume normal subscription usage, and the server decides when a new window starts. If usage cannot be read, timing may be estimated.

A cron command is enough for a fixed daily request; I wanted observed-reset replanning, missed-action handling after sleep, quota visibility, and a menu bar UI together. The Mac must be awake and online. The backend uses Python's standard library, but Python and an authenticated Claude Code installation are still required.

Current setup is a source install on macOS; some planner/bot text is Turkish. Downloadable packaging is still being prepared. Feedback on real reset observations and sleep/wake behavior would be helpful.

GitHub: [GITHUB_URL — https://github.com/aetsr/claude-window-starter]

## Hacker News title

1. Show HN: A Claude Code 5-hour window scheduler for macOS
2. Show HN: Schedule Claude Code warmup requests around work hours
3. Show HN: Claude Code window starter with reset and weekly usage tracking

## X / Twitter post

I built a macOS scheduler for Claude Code's 5-hour window: early requests around work hours, reset tracking, weekly usage and optional Telegram control. Uses normal quota; no limit bypass. Source install today. https://github.com/aetsr/claude-window-starter

## Before posting

Check the community's self-promotion rules, add genuine screenshots, and update the installation status. These drafts have not been posted. Do not claim adoption numbers, endorsements, or guaranteed quota gains.
