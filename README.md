# dependabot-health
What's the health of dependabot usage in an org?

Requires the [GitHub CLI](https://cli.github.com/) (`gh`) to be installed and authenticated.

## Scripts

### dependabot-health.py

Produces either a current Dependabot health report or a weekly historical severity summary for a GitHub org or repo. Current org reports cover all non-archived, non-empty source repos in the org. Current repo reports cover the named repo only.

```
python3 dependabot-health.py <scope>
python3 dependabot-health.py <scope> --history-date YYYY-MM-DD --weeks N
```

`<scope>` can be either an org like `foo` or a repo like `foo/bar`.

Current report output CSV columns:

| Column | Description |
|---|---|
| `repository` | Full repo name |
| `has_dependabot_config` | `True` or `False` |
| `open_count` | Number of unique open advisories |
| `avg_open_age_days` | Mean age in days |
| `p50_open_age_days` | Median age in days |
| `max_open_age_days` | Oldest alert in days |
| `pct_open_over_30d` | % of alerts open longer than 30 days |
| `pct_open_over_90d` | % of alerts open longer than 90 days |
| `open_critical_count` | Number of unique open critical-severity advisories |
| `open_critical_over_30d_count` | Number of unique open critical-severity advisories older than 30 days |
| `open_high_count` | Number of unique open high-severity advisories |
| `open_high_over_60d_count` | Number of unique open high-severity advisories older than 60 days |
| `open_medium_count` | Number of unique open medium-severity advisories |
| `open_medium_over_90d_count` | Number of unique open medium-severity advisories older than 90 days |
| `language` | Primary language |
| `size_kb` | Repo size in KB |
| `created_at` | Repo creation date |
| `pushed_at` | Last push to any branch |
| `last_commit_date` | Date of last commit on default branch |
| `last_commit_author` | GitHub login of last commit author |

A summary line is printed to stderr. Repos with no open alerts still appear in the current report with alert counts set to `0`.

Historical mode outputs one row per week, working backward from `--history-date`, with CSV columns:

| Column | Description |
|---|---|
| `scope` | Org or repo the history was generated for |
| `snapshot_date` | Weekly snapshot date in `YYYY-MM-DD` format |
| `open_count` | Number of unique open advisories on that date |
| `open_critical_count` | Number of unique open critical-severity advisories on that date |
| `open_critical_over_30d_count` | Number of unique open critical-severity advisories that were at least 30 days old on that date |
| `open_high_count` | Number of unique open high-severity advisories on that date |
| `open_high_over_60d_count` | Number of unique open high-severity advisories that were at least 60 days old on that date |
| `open_medium_count` | Number of unique open medium-severity advisories on that date |
| `open_medium_over_90d_count` | Number of unique open medium-severity advisories that were at least 90 days old on that date |

Historical snapshots are inferred from alert `created_at`, `fixed_at`, `dismissed_at`, and `updated_at` timestamps. Reopened alerts can introduce a small amount of historical noise because the REST payload is not a perfect event log.

### alert-age.py

Reports on the age of open Dependabot alerts per repo. Alerts are deduplicated by advisory so the same CVE across multiple manifest files is counted once.

```
python3 alert-age.py <org>
```

Outputs CSV to stdout with columns:

| Column | Description |
|---|---|
| `repository` | Full repo name |
| `open_count` | Number of unique open advisories |
| `avg_open_age_days` | Mean age in days |
| `p50_open_age_days` | Median age in days |
| `max_open_age_days` | Oldest alert in days |
| `pct_open_over_30d` | % of alerts open longer than 30 days |
| `pct_open_over_90d` | % of alerts open longer than 90 days |

Results are sorted worst-first by `pct_open_over_90d`, then `max_open_age_days`, then `open_count`.

### config-coverage.py

Checks which non-archived, non-empty repos in an org have a Dependabot configuration file (`.github/dependabot.yml` or `.github/dependabot.yaml`).

```
python3 config-coverage.py <org>
```

Outputs CSV to stdout with columns:

| Column | Description |
|---|---|
| `repository` | Full repo name |
| `has_dependabot_config` | `True` or `False` |
| `language` | Primary language |
| `size_kb` | Repo size in KB |
| `created_at` | Repo creation date |
| `pushed_at` | Last push to any branch |
| `last_commit_date` | Date of last commit on default branch |
| `last_commit_author` | GitHub login of last commit author |

A summary line is printed to stderr.
