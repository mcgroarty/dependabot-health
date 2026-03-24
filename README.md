# dependabot-health
What's the health of dependabot usage in an org?

Requires the [GitHub CLI](https://cli.github.com/) (`gh`) to be installed and authenticated.

## Scripts

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
