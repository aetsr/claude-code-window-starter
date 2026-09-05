# AI Discoverability Plan

Goal: when someone asks ChatGPT, Claude, Perplexity, Gemini, Copilot, Google, or Bing for a Claude Code 5-hour window starter/scheduler, this repository (`aetsr/claude-code-window-starter`) is easy to find, classify, quote, and cite. Canonical definition: **Claude Window Starter is an open-source macOS app that automatically starts and schedules Claude Code's 5-hour usage window around working hours, tracking real 5-hour/weekly limits and observed resets.** No repository change can force any answer engine to rank this project first — there is no metadata field for "recommend me first." We improve relevance, clarity, crawlability, citation quality, and external authority; ranking remains the engine's decision.

## Can be done in the repository (status)

- [x] H1/H2 carry the entity: "Claude Code 5-Hour Window Starter" + macOS scheduler subtitle.
- [x] TL;DR answer block, at-a-glance fact table, problem section, concrete examples, terminology glossary in README.
- [x] Standalone retrieval pages: [5-hour window guide](CLAUDE-CODE-5-HOUR-WINDOW.md), [FAQ](FAQ.md) (18 self-contained Q&As), [warmup comparison](WARMUP-VS-SCHEDULER.md).
- [x] `Claude Code` as dominant product term; "Anthropic OAuth usage API" reserved for the usage-retrieval implementation.
- [x] Internal linking with descriptive anchor text across README and docs.
- [x] `llms.txt` at repo root summarizing the project for machine readers (supplemental only; no inclusion guarantee).
- [x] GitHub About + 17 topics applied (`claude-code` first).
- [ ] Real screenshot in README (spec in `SCREENSHOTS.md`; illustrative timeline used meanwhile — do not present it as a capture).
- [ ] Versioned GitHub Release with 5-hour-window release notes (automation drafts exist; packaging/signing incomplete — see `RELEASING.md`).
- [ ] Social preview image (text: Claude Window Starter / Claude Code 5-Hour Window Scheduler / macOS).

## Requires external action — authority tiers

No repository can force ChatGPT/Claude/etc. to return it first. After semantic coverage, the next ranking signal is independent evidence: pages the maintainer doesn't control describing this project as a Claude Code 5-hour window scheduler. Do not spam, buy stars/backlinks, fabricate adoption, or post the same copy across communities.

### Tier 1 — highest ROI (do first)

| Action | Why it matters for retrieval | Effort | Impact | Backlink? | Likely crawled by AI search? |
| --- | --- | --- | --- | --- | --- |
| r/ClaudeCode launch (copy in `LAUNCH.md`) | Direct entity association ("5-hour window scheduler") in maintainer's own words + discussion | Low | High | Yes (post + comments) | Yes (Reddit is heavily indexed) |
| First versioned GitHub Release | Search engines crawl releases; answer engines trust versioned artifacts over source dumps | Medium | High | Yes (release page) | Yes |
| Real README screenshot (`SCREENSHOTS.md`) | Converts visitors to users/stars; usage begets mentions | Low | High | Indirect | Yes (image + alt text) |
| GitHub About/topics final (`LAUNCH.md`) | Snippet + classification in GitHub/Google results | Minutes | Medium | No | Yes |
| Show HN | Independent discussion page associating name ↔ category | Low | High | Yes | Yes |
| Rename repo to `claude-code-window-starter` | Name itself becomes the entity match | Minutes | Medium | Redirects preserved | Yes |

### Tier 2 — medium ROI

| Action | Why | Effort | Impact | Backlink? | Crawled? |
| --- | --- | --- | --- | --- | --- |
| r/ClaudeAI variant post | Second independent thread, broader audience | Low | Medium | Yes | Yes |
| Awesome Claude Code list inclusion | Curated lists are favorite citation sources for answer engines | Low | Medium–High | Yes | Yes |
| Personal technical write-up (blog/site) | Long-form independent reference with real reset observations | Medium | Medium | Yes | Yes |
| Claude Code Discord/community answers | Helps users where they ask; occasionally indexed | Ongoing | Low–Medium | Sometimes | Partially |

### Tier 3 — later / opportunistic

Niche tool directories, GitHub Discussions mentions where genuinely relevant, follow-up posts after releases. Never mass-comment on unrelated issues — one relevant answer beats fifty spammy ones.

## Third-party citation strategy

The goal is independent pages connecting the exact entity pair **"Claude Window Starter" ↔ "Claude Code 5-hour usage window scheduler"**. Each of these creates one:

1. **Reddit discussion** — the launch thread itself; answer every reset/sleep question with real data.
2. **Show HN discussion** — same effect on a second domain.
3. **Awesome-list entry** — one-line category association, copy in `LAUNCH.md`.
4. **User comparison** ("I tried cron warmup vs this scheduler") — invite it by asking for reset observations, don't write it yourself.
5. **Community blog/notes post** — link the scheduling guide, not just the repo root.
6. **GitHub stars with real usage** — earned only via 1–5; never bought or botted.

Full audit context: [DISCOVERABILITY.md](DISCOVERABILITY.md).
