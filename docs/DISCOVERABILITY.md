# Discoverability audit and checklist

Audit date: 2026-09-05. Scope: tracked repository, scheduling/backend/Swift code, scripts, tests, CI, docs, public About/topics and GitHub Releases. No repository rename, metadata update, tag push, release publication or social post was performed. Scores are editorial judgments of clarity/readiness, not measured search rankings.

## Findings ranked by severity

1. **High — wrong search category.** GitHub About said “macOS app for scheduling Claude API usage windows — Telegram bot, atomic releases, zero runtime deps”. It omitted Claude Code and five-hour timing. Topics were `anthropic automation claude macos python scheduler swift telegram-bot`; `claude-code` was absent.
2. **High — installation/release claims.** No GitHub Releases were returned. The app bundle contains Swift executables, not the external backend/venv it calls. Source installation needs Python and Swift 6; old docs said Swift 5.9/Xcode 15 and zero runtime dependencies. Installer activation precedes app build without documented automatic health rollback.
3. **High — trust gap.** “Maximizes subscription quota”, instant/subsecond usage reads and immutable health-gated releases were stronger than the implementation supports. OAuth uses a bearer header in curl argv; the security docs described only the PTY fallback. Disclaimers were absent.
4. **Medium — product hidden by architecture.** The hero sold a tracker/menu app and technical properties before early scheduling. The ASCII UI looked like a product preview despite no actual screenshot. A fixed test-count badge and a 2.2.0 badge obscured the actual 2.1.0 package version.
5. **Medium — conversion friction.** Missing clone/auth steps, duplicated builds, a rollback command without required `--yes`, and pytest instructions without the source path or pytest in dev requirements. Mixed English/Turkish UI and replies remain a first-run limitation.
6. **Medium — release quality checks already red.** Three lint violations and three formatting violations existed before the audit. Minimal cleanup repairs them without scheduling/auth changes.

## Product claims and implementation evidence

| Question | Finding | Evidence |
| --- | --- | --- |
| Primary problem | Schedule early legitimate Claude Code usage around work hours and inspect subsequent resets | `scheduler.py:ideal_actions_for_day`, `claude.py:run_anchor` |
| Does it start a window? | Sends fixed Haiku/tool-free request; eligible usage may open a window, success alone is not server confirmation | `claude.py:ANCHOR_PROMPT`, `run_anchor`, `run_claude` |
| Default plan | Three-hour lead, clamped to midnight; 303-minute intervals to work end; weekdays configured | `scheduler.py:ideal_actions_for_day`, `config/config.example.json` |
| Adaptive behavior | At due action: query usage; skip/replan active window from reset + grace; suppress observed weekly exhaustion | `scheduler.py:tick_schedule`, `_replan_from_observation` |
| Observation failures | Estimated-confidence anchor can still run | `scheduler.py:tick_schedule` |
| Reset detection | OAuth `resets_at`; otherwise parsed CLI `/usage`; local calculations/calibration are estimates | `usage.py:_api_response_to_result`, `parse_usage_limits`, `windows.py` |
| Freshness | Cache can be reused for 300 seconds, even on sync; scheduler snapshot uses a 900-second observation cutoff | `usage.py:_read_usage_cache`, `scheduler.py:_fresh_observation` |
| Weekly quota | Parses usage percent/reset from `weekly_all` or `seven_day`, or CLI text; used in output and scheduler checks | `usage.py`, `AppModel.swift`, `telegram_bot.py` |
| Sleep/network | Swift power assertions/network monitor; no wake scheduling; stale actions expire and manual windows can need recalibration | `BackgroundAgent.swift`, `cli.py` connectivity handling, `scheduler.py` |
| Telegram | Private allowlists, pairing, confirmed run/prompt changes; real commands listed in README | `telegram_bot.py:_command`, `KeychainStore.swift` |
| Runtime | Python >=3.10, Claude Code subscription login, macOS utilities; no third-party Python packages | `pyproject.toml`, `BackendClient.swift`, `usage.py` |
| Build | Swift tools 6.0, macOS 13 deployment target; native host build, ad-hoc signing | `Package.swift`, `Info.plist`, build scripts |
| Releases | No GitHub Releases at audit; local v1.0.0 tag; current package/app 2.1.0; former 2.2.0 notes unshipped | GitHub CLI, version files, changelog |
| Security | Restricted CLI requests; OAuth argv exposure and broad Telegram Keychain access remain documented concerns | `usage.py:_query_usage_api`, `claude.py`, `KeychainStore.swift` |

The repo's `maximize_quota` strategy name is an internal identifier, not evidence of increased server quota. Internal identifiers and installed paths were preserved. “Claude API usage windows” is misleading as a public product category; OAuth usage inspection is an accurate implementation term.

## Repository metadata

- [x] Read live About/topics and release list.
- [x] Prepare three ranked descriptions in [LAUNCH.md](LAUNCH.md).
- [x] Recommend `claude-code-window-starter`; current name is acceptable but less specific.
- [ ] Set About to: **Schedule Claude Code's 5-hour usage window before work. macOS starter with reset tracking, weekly quota monitoring, adaptive work-hours planning and Telegram control.**
- [ ] Optionally rename the repository; update public URLs/badges afterward, preserving local application identity.
- [ ] Add a real GitHub social preview image.

## README

- [x] Lead with Claude Code five-hour scheduling, not architecture.
- [x] Explain legitimate requests, consumption of quota and server authority.
- [x] Add non-bypass and affiliation disclaimers.
- [x] Distinguish cached observations from estimated schedules.
- [x] Separate install, artifact build and runtime requirements.
- [x] Add work-hours example, quick start, cron differentiation and FAQ.
- [x] Correct local commands and remove static test/version badges.
- [x] Document current mixed-language interface rather than claiming complete English localization.

## Releases

- [x] Add tag-triggered draft artifact workflow and checksums.
- [x] Add release notes template and SemVer consistency validation.
- [x] Correct unreleased 2.2.0 labeling without fabricating a release or version bump.
- [x] Explain ZIP/DMG tradeoffs, Python bundling and signing requirements in [RELEASING.md](RELEASING.md).
- [ ] Complete backend/runtime installation packaging for clean Macs.
- [ ] Make install/rollback coherent across backend, app and launchd jobs; test failure recovery.
- [ ] Resolve OAuth argv exposure and review Keychain ACLs before broad distribution.
- [ ] Supply Developer ID/notarization credentials and implement the documented signed stage once packaging is complete.
- [ ] Validate clean machines and each advertised architecture/macOS version.
- [ ] Choose/bump next version consistently, push its tag, review workflow draft and publish manually.

## Screenshots

- [x] Audit tracked assets; no real product captures exist.
- [x] Add honest illustrative timeline and screenshot insertion comment.
- [x] Specify dimensions, content, privacy review and alt text in [SCREENSHOTS.md](SCREENSHOTS.md).
- [ ] Capture actual planner and usage views; add reviewed relative image links.
- [ ] Capture work-hours settings, Telegram status and optional short GIF.

## GitHub Topics

- [x] Prepare ranked list: `claude-code`, `claude-code-usage`, `5-hour-window`, `scheduler`, `usage-limit`, `usage-tracking`, `warmup`, `macos`, `menu-bar`, `claude-code-quota`, `quota`, `automation`, `claude`, `anthropic`, `telegram-bot`.
- [x] Check topic syntax/count against [GitHub's rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics): lowercase letters/numbers/hyphens, <=50 characters each, <=20 topics.
- [ ] Apply topics in GitHub settings. Niche topics are valid; popularity and ranking benefit are unverified.

## External distribution

- [ ] Publish complete, verified downloads before advertising one-click installation.
- [ ] Consider a personal Homebrew tap after packaging/signing; review [Cask acceptance rules](https://docs.brew.sh/Acceptable-Casks) before proposing upstream inclusion.
- [ ] Submit to relevant Claude Code/macOS tool directories that accept independent projects.
- [ ] Check indexing after metadata/docs land. Semantic coverage does not ensure Google/GitHub ranking.

## Community launch

- [x] Prepare five Reddit titles, one post, three HN titles and an X post in [LAUNCH.md](LAUNCH.md).
- [ ] Check each community's rules and publish manually with genuine screenshots.
- [ ] Invite reproducible feedback; answer installation and limit-behavior questions.
- [ ] Add social proof only when earned; no fabricated testimonials, stars, forks or endorsements.

## Future improvements

- [ ] Complete English localization and make timezone defaults consistent across config/UI/output.
- [ ] Add a genuine force-refresh path if needed; current sync honors the cache.
- [ ] Expand OAuth-specific tests and verify token discovery/endpoint compatibility across Claude Code versions.
- [ ] Consider post-anchor observation to distinguish request success from confirmed server-window start.
- [ ] Add end-user packaging and clean-install verification before a polished download CTA.

## Search-intent simulation

These are semantic matches in the revised text, not live search position measurements.

| Query | Matching repository text | Assessment |
| --- | --- | --- |
| Claude Code 5 hour limit starter | Title “Claude Code 5-Hour Window Starter”; hero “usage limit” and “scheduler and starter” | Strong |
| start Claude Code 5 hour window early | Hero “before work”; FAQ “Can I start … before I begin working?”; 05:00 example | Strong, bounded by server eligibility |
| Claude Code warmup macOS | Hero macOS; FAQ “Is this a Claude Code warmup tool?” | Strong |
| Claude Code usage reset scheduler | Hero “usage reset”; scheduling section and reset-plus-grace behavior | Strong |
| Claude Code 5h quota tracker | Hero “5h and weekly quota tracking”; Features usage percentages | Strong |
| Claude Code weekly usage menu bar | Hero “macOS menu bar” and “weekly quota tracking”; weekly FAQ | Strong |
| schedule Claude Code usage window around work hours | Value proposition, Quick start and explicit three-hour lead/workday example | Strong |

Other initial phrases—“5h reset”, “reset timer”, “usage limit”, “quota tracker”—are covered by reset/countdown explanations, limit disclaimer and tracking language. An explicit server reset button would be a misleading promise and is not offered.

## Scores (0–10)

“After” means local improvements plus recommended metadata where indicated. Actual remote metadata remains unchanged.

| Area | Before | After / recommendation | Remaining constraint |
| --- | ---: | ---: | --- |
| Repo name | 7 | 9 if renamed | Current name remains 7 |
| GitHub About | 3 | 9 if applied | Manual |
| Topics | 4 | 9 if applied | Manual |
| README hero | 4 | 9 | Actual screenshot missing |
| Search intent coverage | 4 | 9 | Indexing/ranking unmeasured |
| Installation conversion | 3 | 5 | Source build still required |
| Visual presentation | 2 | 3 | No real product image |
| Release readiness | 2 | 4 | Draft automation, incomplete distribution |
| Social proof readiness | 2 | 4 | Launch copy ready; no fabricated adoption |
| Overall discoverability | 4 | 6 now; 8 with metadata applied | Downloads/screenshots still limit conversion |

## Validation record

Baseline: 244 Python unit tests and 7 XCTest tests passed; Ruff had three lint errors and three files needing formatting.

Final verification on Apple Silicon: `scripts/build-local.sh` passed, including 244 Python tests, 7 XCTest tests, Python compilation, security scan, isolated wheel installation/version smoke test without source PYTHONPATH, plist validation, release Swift build and ad-hoc signature verification. Ruff lint/format, mypy, Bandit, shell syntax and `git diff --check` passed. Local links and script paths in 12 documents, Telegram command names, workflow YAML, and release version checks (matching and deliberately mismatched tags) passed. ZIP/source archive packaging, ZIP integrity and SHA-256 verification passed. The first sandboxed build failed to reach PyPI; rerunning with approved network access succeeded. A pre-existing `SecAccessCreate` deprecation warning remains.

No live Claude request, Telegram message, installed-app replacement or LaunchAgent mutation was used for the audit. The source installer was inspected/syntax-checked, not executed against the user's active installation. Clean-machine/Intel behavior and GitHub-hosted release execution remain unverified. Local packaging smoke tests used committed HEAD for the source archive and are not release deliverables.
