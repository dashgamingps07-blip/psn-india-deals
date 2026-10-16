# PSN India Discord Deals (free, experimental)

Hourly scheduled checks of the PSPrices PS5/PS4 India **table page**, sending newly observed >=50%-off offers to a Discord webhook. Initial run records a baseline without mass posting. No Discord bot token needed.

## Setup

1. In Discord, create channel `#psn-deals` -> Edit Channel -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL. **Treat webhook as a password.**
2. Create a **public** GitHub repository (e.g. `psn-india-deals`). Upload `bot.py`, `requirements.txt`, `.github/workflows/deals.yml` and this README, keeping the exact folder structure. For privacy, don't put your webhook in files.
3. GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret -> name `DISCORD_WEBHOOK_URL` -> paste webhook URL.
4. GitHub repo -> Actions -> `PSN India Deals` -> Run workflow. Check green run & log: `Baseline initialized...`. `seen.json` should be committed automatically.
5. From then on GitHub checks hourly and posts NEW/CHANGED offers (up to 12 per run). Check Actions log if no posts.

## Tuning

In `.github/workflows/deals.yml`, change `MIN_DISCOUNT: '50'` (e.g., 70), `PAGES: '2'` (1–5), `MAX_POSTS: '12'`. For a one-time test post, add `TEST_POST: 'true'` alongside those env entries, manually run, and **remove afterward**. This test posts a live observed listing without updating history.

## Limits

- **Unverified scraper:** PSPrices has no confirmed supported free public API for this use. HTML layout may change or automated access may be blocked; respect their site's access and usage rules. If unavailable, this approach stops and logs an error. We have **not** end-to-end-tested live collection/Discord delivery.
- PSPrices listing says updated hourly. GitHub's scheduled runs may start late. Neither are real-time event pushes.
- Fetches only first 2 pages sorted by update date: **not all existing sale items**. Discounts >=50% only; links go to PSPrices rather than direct PS Store. Checks may list other market content if site's platform filters change.
- Github public repositories have free standard Actions runner usage. This may change; check GitHub billing rules.
