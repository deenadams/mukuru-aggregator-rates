# Mukuru Aggregator Rates Snapshot

Scheduled GitHub Action that pulls Mukuru's Taurus Rates API daily, ranks payout
partners per corridor, flags switch-off candidates, and publishes the result
as JSON for the Aggregator Dashboard's "Aggregator Switching" tab to read.

No server runs continuously — the workflow (`.github/workflows/snapshot.yml`)
fires on a cron schedule, calls the API using repo secrets, and commits the
result to `docs/`.

## Output

- `docs/snapshot.json` — current ranking: per corridor, all providers, the
  best enabled option, whether a better disabled option exists, and per-partner
  keep/switch-off verdicts.
- `docs/history.json` — rolling per-corridor-per-provider deviation-vs-mid-rate
  time series (180-day retention), for the trend chart.

Read via the repo's raw GitHub URL — this repo and its `docs/` output are
public, so there's no login gate on this data (a deliberate simplicity
trade-off — see the Aggregator Dashboard project notes).

## Config

Repo secrets: `TAURUS_CLIENT_ID`, `TAURUS_CLIENT_SECRET_STAGING`,
`TAURUS_CLIENT_SECRET_PROD`, `TAURUS_TOKEN_URL_STAGING`, `TAURUS_TOKEN_URL_PROD`,
`TAURUS_API_URL_STAGING`, `TAURUS_API_URL_PROD`, `TAURUS_SCOPE`.

Repo variable `TAURUS_ENV` = `staging` (default) or `production` — switches
which secret pair the workflow uses. Currently pinned to staging until the
production token URL is available.

## Run locally

```bash
export TAURUS_TOKEN_URL=... TAURUS_API_URL=... TAURUS_CLIENT_ID=prism \
       TAURUS_CLIENT_SECRET=... TAURUS_SCOPE=valtaurus.pricing-analyst
python3 scripts/fetch_and_rank.py
```
