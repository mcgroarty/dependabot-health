#!/usr/bin/env python3

import argparse
import csv
import json
import math
import subprocess
import sys
from datetime import datetime, timezone


def fetch_alerts(org):
    result = subprocess.run(
        [
            "gh", "api",
            "--method", "GET",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10",
            f"/orgs/{org}/dependabot/alerts?state=open&sort=created&direction=asc&per_page=100",
            "--paginate",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error fetching alerts: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # --paginate outputs multiple JSON arrays; concatenate them
    alerts = []
    decoder = json.JSONDecoder()
    text = result.stdout.strip()
    pos = 0
    while pos < len(text):
        # skip whitespace between JSON arrays
        while pos < len(text) and text[pos] in " \t\n\r":
            pos += 1
        if pos >= len(text):
            break
        obj, end = decoder.raw_decode(text, pos)
        if isinstance(obj, list):
            alerts.extend(obj)
        else:
            alerts.append(obj)
        pos = end

    return alerts


def compute_stats(alerts):
    now = datetime.now(timezone.utc)

    # Deduplicate: keep one entry per (repo, advisory) using the earliest created_at
    unique = {}
    for alert in alerts:
        repo = alert["repository"]["full_name"]
        ghsa_id = alert.get("security_advisory", {}).get("ghsa_id", alert["number"])
        created_at = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
        key = (repo, ghsa_id)
        if key not in unique or created_at < unique[key]:
            unique[key] = created_at

    # Group by repo
    repos = {}
    for (repo, _), created_at in unique.items():
        age_days = (now - created_at).total_seconds() / 86400
        repos.setdefault(repo, []).append(age_days)

    rows = []
    for repo, ages in repos.items():
        ages_sorted = sorted(ages)
        count = len(ages)
        midpoint = count // 2
        if count % 2 == 1:
            p50_age = math.floor(ages_sorted[midpoint])
        else:
            p50_age = math.floor((ages_sorted[midpoint - 1] + ages_sorted[midpoint]) / 2)
        rows.append({
            "repository": repo,
            "open_count": count,
            "avg_open_age_days": math.floor(sum(ages) / count),
            "p50_open_age_days": p50_age,
            "max_open_age_days": math.floor(max(ages)),
            "pct_open_over_30d": math.floor(sum(1 for a in ages if a >= 30) / count * 100),
            "pct_open_over_90d": math.floor(sum(1 for a in ages if a >= 90) / count * 100),
        })

    rows.sort(key=lambda r: (r["pct_open_over_90d"], r["max_open_age_days"], r["open_count"]), reverse=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Report on Dependabot alert health for a GitHub org.")
    parser.add_argument("org", help="GitHub organization name")
    args = parser.parse_args()

    alerts = fetch_alerts(args.org)
    if not alerts:
        print("No open Dependabot alerts found.", file=sys.stderr)
        sys.exit(0)

    rows = compute_stats(alerts)

    fieldnames = [
        "repository",
        "open_count",
        "avg_open_age_days",
        "p50_open_age_days",
        "max_open_age_days",
        "pct_open_over_30d",
        "pct_open_over_90d",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
