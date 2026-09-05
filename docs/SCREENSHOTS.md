# Real product capture checklist

No product screenshots or GIFs were tracked at audit time; only the app icon exists. The README includes a clearly labeled illustrative schedule and a screenshot insertion comment. Do not substitute generated UI images for actual captures.

Save reviewed captures under `docs/images/` using stable names. Capture at native Retina resolution, crop unrelated desktop content, and redact tokens, pairing codes, user/chat IDs, account names and private messages. Preserve genuine usage values; do not fabricate favorable states.

| Capture | Suggested pixels | What to show | Suggested alt text |
| --- | --- | --- | --- |
| `automation.png` | about 1160 × 1280 (580 × 640 points at 2×), taller if needed | Real Automation tab: work hours, anchor preview, observed reset, source/freshness, next action | Claude Code five-hour scheduler showing work hours, planned requests and observed reset |
| `usage.png` | 1160 px wide, cropped to actual content | Five-hour and weekly percentages and available reset/countdown information in the actual usage view | Claude Code five-hour and weekly usage with reset information |
| `work-hours.png` | 1160 × 700, adjust to avoid clipping | Start/end fields, timezone, Save and enabled state | Work-hours settings for early Claude Code window requests |
| `telegram.png` | about 900 × 1200 | Genuine `/usage` and `/schedule` replies without identifying chat information | Telegram usage and schedule replies from Claude Code Window Starter |
| `automation.gif` (optional) | 800–1000 px wide, 8–12 seconds, ideally under 5 MB | Save hours, inspect plan, enable automation; keep text readable | Enabling Claude Code work-hours scheduling |

The current app mixes English and Turkish. Capture it honestly. If all requested usage fields cannot fit in the menu window, use two captures rather than assembling a fake combined UI.

After reviewing a real capture, replace the README comment with:

```markdown
![Claude Code five-hour scheduler showing work hours, planned requests and observed reset](docs/images/automation.png)
```

**Hero pick:** `automation.png` is the single screenshot for the top of the README — it must show 5h usage, weekly usage, reset time/countdown, next scheduled anchor, and automation status in one crop. `usage.png` and `work-hours.png` support lower sections; do not put three screenshots in the hero.

Use a real screenshot crop and the product title for a 1280 × 640 GitHub social preview. Uploading the social preview is a manual repository settings action.
