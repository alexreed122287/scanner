# Daily Picks Email

Sends you a morning digest of bullish setups (the same `call% ≥ 70 + net GEX > 0` filter the dashboard's BULL ★ column uses), with the top 3 ITM call contracts per ticker.

## What gets sent

Every weekday at **8 AM CDT / 7 AM CST** (configurable via the cron entry in `.github/workflows/daily_picks.yml`), you receive an HTML email with:

- Ticker, sector, theme
- Live spot price + intraday % change
- GEX flow (call %, net GEX in $M)
- Top 3 ITM call contracts in the 25–50 DTE window (strike, expiry, mid premium, OI, delta)

Up to 10 tickers per email (set via `DAILY_PICKS_MAX_PICKS` repo variable).

## Setup

You only need to do this once. The workflow soft-fails (exits 0) if any secret is missing, so you can leave the schedule on while you sort out email.

### 1. Sign up for Resend

[Resend.com](https://resend.com) free tier covers 3 000 emails/month — fine for daily single-recipient mail.

1. Create an account.
2. Add and verify a sending domain (or use Resend's onboarding "from email").
3. Generate an API key (Dashboard → API Keys → Create).

### 2. Add GitHub secrets

In the repo's **Settings → Secrets and variables → Actions**, add three repo secrets:

| Name              | Value                                                       |
|-------------------|-------------------------------------------------------------|
| `RESEND_API_KEY`  | `re_xxxxx...` from Resend                                   |
| `EMAIL_TO`        | the address you want the digest sent to                     |
| `EMAIL_FROM`      | a verified sender address on your Resend domain             |

(`TRADIER_TOKEN` is already configured for the GEX cron — same value reused.)

### 3. (Optional) Tweak thresholds

In **Settings → Secrets and variables → Actions → Variables**, add:

- `DAILY_PICKS_MIN_CALL_PCT` — defaults to `70`. Lower (e.g. 65) for more picks, higher (e.g. 75) for stricter conviction.
- `DAILY_PICKS_MAX_PICKS` — defaults to `10`. Hard cap on tickers in the email.

### 4. (Optional) Change the send time

Edit the `cron:` line in `.github/workflows/daily_picks.yml`:

```yaml
- cron: "0 13 * * 1-5"   # 13:00 UTC = 8 AM CDT / 7 AM CST, Mon–Fri
```

Use [crontab.guru](https://crontab.guru) to translate. GitHub schedules in UTC — the comment in the workflow file lists common conversions.

### Manual test

Go to **Actions → Daily Picks Email → Run workflow → main → Run**. Confirms the secrets are configured and the email actually delivers.

## How it works

```
gex/gex_scores.json   ← GEX cron writes this 3×/day
industry/theme_scores.json ← theme cron writes this daily
              │
              ▼
daily_picks/run_daily_picks.py
   • Filters gex_scores.json for bullish setups
   • Re-fetches Tradier quotes + chains for top picks (top-3 ITM calls)
   • Looks up sector/theme per ticker
   • Renders HTML email
   • POSTs to Resend API
```

No new in-page scoring — the bullish filter mirrors the dashboard's BULL ★ formula. If the dashboard's threshold changes (e.g. `BULLISH_CALL_PCT` is retuned), update `DAILY_PICKS_MIN_CALL_PCT` to match.
