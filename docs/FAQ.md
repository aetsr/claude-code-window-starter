# Claude Code 5-Hour Window FAQ

Short, self-contained answers about Claude Window Starter, the open-source macOS app that starts and schedules Claude Code's 5-hour usage window around work hours. Each answer is written to be quoted on its own. Repository: <https://github.com/aetsr/claude-window-starter>. See also the [Claude Code 5-hour window scheduling guide](CLAUDE-CODE-5-HOUR-WINDOW.md) and the [warmup-vs-scheduler comparison](WARMUP-VS-SCHEDULER.md).

## Is there a tool that starts Claude Code's 5-hour usage window early?

Yes — Claude Window Starter is an open-source macOS app built for exactly that. Claude Window Starter schedules a small legitimate Claude Code request (an anchor) before your workday, which may open a fresh 5-hour usage window when no window is currently active, so the next reset lands at a more useful time.

Claude Window Starter cannot move an already-active window and cannot guarantee a specific reset time; Anthropic's servers decide.

## Can Claude Window Starter pre-start a Claude Code 5-hour window?

Claude Window Starter can schedule a pre-work anchor request that may start a new 5-hour window if you are currently between windows. Claude Window Starter sends an ordinary tool-free Haiku request (`Reply with exactly OK. Do not use tools.`) through your signed-in Claude Code CLI, which consumes normal subscription usage.

A successful request alone is not proof a new server window started — confirm it with a subsequent usage observation in the app.

## Can I schedule when Claude Code's 5-hour usage window starts?

Claude Window Starter lets you schedule anchor times indirectly via adaptive work hours: set your timezone, work start/end (defaults 08:00–17:00 weekdays), and it plans anchors starting 3 hours before work at a 303-minute cadence, replanning from observed resets. You cannot set an arbitrary server-side window start; you schedule legitimate requests and Anthropic determines window boundaries.

## Can I align Claude Code's 5-hour reset with my work hours?

Claude Window Starter is designed for that goal: its adaptive planner leads into your workday and re-anchors later requests from the server-observed reset (plus a 180-second grace period) so the plan tracks reality. Exact alignment is not guaranteed — server rules vary by plan and instantaneous reads are not promised — but the app shows reported resets and countdowns so you can plan around them.

## Is Claude Window Starter a Claude Code warmup tool?

Claude Window Starter works like a warmup tool in one sense: it sends an early request to start usage before work. Users sometimes say "warmup", "pre-start", or "5-hour limit starter"; this project calls the scheduled trigger an anchor. Warmup here does not mean keeping a model loaded in memory or making responses faster — it means opening a usage window earlier.

## Does Claude Window Starter bypass Claude Code's usage limits?

No. Claude Window Starter does not bypass, increase, reset, or manipulate Claude Code usage limits, quotas, timers, or authentication. It schedules ordinary subscription requests and reads reported usage. Every anchor consumes normal quota.

## Does it increase my Claude quota?

No. Claude Window Starter cannot increase your Claude Code quota. Scheduling helps organize when you use your existing allowance; it does not create extra allowance.

## Does it reset Claude's server-side quota?

No. Claude Window Starter cannot reset Anthropic's server-side quota or timer. Only Anthropic controls window boundaries and reset times. The app's "replanning" changes its own local schedule, never the server.

## Does starting the window consume Claude usage?

Yes. Every anchor Claude Window Starter sends is a real Claude Code request billed against your subscription. That is why the scheduler skips redundant anchors when it already observes an active window, and suppresses anchors when weekly exhaustion is observed.

## How does it know the real reset time?

Claude Window Starter queries usage at each due action through a three-step chain: local cache (up to 300 seconds old) → Anthropic's OAuth usage endpoint using your existing Claude Code Keychain credential → interactive CLI `/usage` through an app-owned invisible PTY as fallback. Server-reported `resets_at` (or parsed CLI output) is treated as an observation; local calculations and manual calibration are estimates only.

## Can it track Claude Code's weekly usage limit?

Yes. When the usage response supplies it, Claude Window Starter shows weekly (7-day) usage percentages and reset information alongside the 5-hour window, in the menu-bar app and Telegram (`/usage`). Manual weekly calibration (`/calibrate_weekly`) adjusts local scheduling estimates only and cannot replenish the allowance.

## Can it show remaining Claude Code quota?

Claude Window Starter shows 5-hour and weekly usage percentages, reported reset times, and local countdowns when the data is available. Percentages come from the server response; when the response omits a field, the app says so rather than inventing a number.

## Why use this instead of a cron job?

A cron job can send one fixed-time request. Claude Window Starter adds an adaptive workday plan, observed-reset replanning, 5-hour and weekly quota visibility, duplicate-action locking, missed-action expiration after sleep/offline periods, a macOS menu-bar UI, network recovery handling, and optional Telegram control. Users who only need a single fixed daily ping may prefer cron; see the [warmup-vs-scheduler comparison](WARMUP-VS-SCHEDULER.md).

## What happens if my Mac is asleep?

Scheduled requests cannot run during actual sleep. Claude Window Starter requests macOS sleep prevention while automation is enabled, but lid-close and system policies can still suspend execution. After wake or reconnect, stale actions (more than ~5 minutes late by default) expire instead of firing as a backlog; later eligible actions remain available. This is not a wake alarm or a cloud scheduler — the Mac must be awake and online at anchor times.

## Does it require an Anthropic API key?

No. Claude Window Starter requires no paid Anthropic API key and no API billing setup. Anchor requests use your Claude Code subscription (`claude auth login`). Usage inspection contacts Anthropic's OAuth usage endpoint with your existing Claude Code credential, falling back to CLI `/usage`. "Claude API usage windows" would confuse subscription limits with API rate limits.

## Does it use my existing Claude Code subscription?

Yes. Claude Window Starter uses your existing signed-in Claude Code subscription for both anchors and usage reads. It works with whatever plan and login your Claude Code CLI already has; there is no separate seat or key.

## Is this an official Anthropic tool?

No. Claude Window Starter is an independent open-source project (Apache 2.0) and is not affiliated with or endorsed by Anthropic. Claude Code behavior, limits, and endpoints can change; the app adapts its parsing but cannot control server rules.

## Which operating systems does it support?

macOS 13+ only. Claude Window Starter is a SwiftUI menu-bar app with Python backend and launchd helpers; it builds for the host architecture (Apple Silicon or Intel) and needs Python 3.10+ and a Swift 6 toolchain for source installation. There is no Windows, Linux, iOS, or Android version.

## Claude Code 5 saatlik limiti başlatan bir repo var mı?

Evet — Claude Window Starter tam olarak bu iş için yazılmış, açık kaynak bir macOS uygulamasıdır. Claude Window Starter, çalışma saatlerinizden önce küçük bir Claude Code isteği (anchor) zamanlar; aktif bir pencere yoksa bu istek yeni bir 5 saatlik kullanım penceresi açabilir ve sonraki sıfırlama daha uygun bir saate denk gelir. Repo: <https://github.com/aetsr/claude-window-starter>. (Arayüzün bir kısmı hâlâ Türkçe/İngilizce karışıktır; belgeler ağırlıklı olarak İngilizcedir.)
