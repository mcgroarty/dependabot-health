#!/usr/bin/env python3

import argparse
import csv
import json
import math
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta, timezone

API_VERSION = "2026-03-10"
SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
CURRENT_REPORT_FIELDNAMES = [
    "repository",
    "has_dependabot_config",
    "open_count",
    "avg_open_age_days",
    "p50_open_age_days",
    "max_open_age_days",
    "pct_open_over_30d",
    "pct_open_over_90d",
    "open_critical_count",
    "open_critical_over_30d_count",
    "open_high_count",
    "open_high_over_60d_count",
    "open_medium_count",
    "open_medium_over_90d_count",
    "open_low_count",
    "open_unknown_count",
    "language",
    "size_kb",
    "created_at",
    "pushed_at",
    "last_commit_date",
    "last_commit_author",
]
HISTORY_REPORT_FIELDNAMES = [
    "scope",
    "snapshot_date",
    "open_count",
    "open_critical_count",
    "open_critical_over_30d_count",
    "open_high_count",
    "open_high_over_60d_count",
    "open_medium_count",
    "open_medium_over_90d_count",
    "open_low_count",
    "open_unknown_count",
]


def run_gh_api(endpoint, paginate=False, allow_not_found=False):
    command = [
        "gh", "api",
        "--method", "GET",
        "-H", "Accept: application/vnd.github+json",
        "-H", f"X-GitHub-Api-Version: {API_VERSION}",
        endpoint,
    ]
    if paginate:
        command.append("--paginate")

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if allow_not_found and "HTTP 404" in stderr:
            return None
        raise RuntimeError(f"Error fetching {endpoint}: {stderr}")

    if paginate:
        return parse_paginated_json(result.stdout)

    return json.loads(result.stdout)


def parse_paginated_json(text):
    items = []
    decoder = json.JSONDecoder()
    text = text.strip()
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos] in " \t\n\r":
            pos += 1
        if pos >= len(text):
            break
        obj, end = decoder.raw_decode(text, pos)
        if isinstance(obj, list):
            items.extend(obj)
        else:
            items.append(obj)
        pos = end
    return items


def parse_scope(scope):
    parts = scope.split("/")
    if len(parts) == 1:
        return {"kind": "org", "org": scope, "repo": None, "name": scope}
    if len(parts) == 2 and all(parts):
        return {"kind": "repo", "org": parts[0], "repo": scope, "name": scope}
    raise RuntimeError(
        f"Invalid scope '{scope}'. Use either an org name like 'foo' or a repo name like 'foo/bar'."
    )


def fetch_repos(org):
    repos = run_gh_api(f"/orgs/{org}/repos?type=sources&per_page=100", paginate=True)
    repos = [repo for repo in repos if not repo["archived"] and repo.get("size", 0) > 0]
    repos.sort(key=lambda repo: repo["full_name"])
    return repos


def fetch_repo(repo_full_name):
    return run_gh_api(f"/repos/{repo_full_name}")


def fetch_open_alerts(scope_info):
    if scope_info["kind"] == "org":
        endpoint = (
            f"/orgs/{scope_info['org']}/dependabot/alerts?"
            "state=open&sort=created&direction=asc&per_page=100"
        )
    else:
        endpoint = (
            f"/repos/{scope_info['repo']}/dependabot/alerts?"
            "state=open&sort=created&direction=asc&per_page=100"
        )
    return run_gh_api(endpoint, paginate=True)


def fetch_historical_alerts(scope_info):
    state_filter = "open,fixed,dismissed,auto_dismissed"
    if scope_info["kind"] == "org":
        endpoint = (
            f"/orgs/{scope_info['org']}/dependabot/alerts?"
            f"state={state_filter}&sort=created&direction=asc&per_page=100"
        )
    else:
        endpoint = (
            f"/repos/{scope_info['repo']}/dependabot/alerts?"
            f"state={state_filter}&sort=created&direction=asc&per_page=100"
        )
    return run_gh_api(endpoint, paginate=True)


def has_dependabot_config(repo_full_name):
    for filename in ("dependabot.yml", "dependabot.yaml"):
        response = run_gh_api(
            f"/repos/{repo_full_name}/contents/.github/{filename}",
            allow_not_found=True,
        )
        if response is not None:
            return True
    return False


def get_last_commit(repo_full_name):
    data = run_gh_api(f"/repos/{repo_full_name}/commits?per_page=1")
    if not data:
        return {"last_commit_date": "", "last_commit_author": ""}

    commit = data[0]
    return {
        "last_commit_date": commit["commit"]["committer"]["date"],
        "last_commit_author": (commit.get("author") or {}).get("login", ""),
    }


def parse_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def advisory_key(alert):
    security_advisory = alert.get("security_advisory") or {}
    return security_advisory.get("ghsa_id") or security_advisory.get("summary") or alert["number"]


def advisory_severity(alert):
    security_advisory = alert.get("security_advisory") or {}
    security_vulnerability = alert.get("security_vulnerability") or {}
    severity = (security_advisory.get("severity") or security_vulnerability.get("severity") or "").lower()
    return severity if severity in SEVERITY_RANK else ""


def deduplicate_open_alerts(alerts):
    unique = {}
    for alert in alerts:
        repo = alert["repository"]["full_name"]
        key = (repo, advisory_key(alert))
        created_at = parse_timestamp(alert["created_at"])
        severity = advisory_severity(alert)
        record = unique.get(key)

        if record is None:
            unique[key] = {"created_at": created_at, "severity": severity}
            continue

        if created_at < record["created_at"]:
            record["created_at"] = created_at

        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(record["severity"], 0):
            record["severity"] = severity

    return unique


def closure_timestamp(alert):
    candidates = [
        parse_timestamp(alert.get("fixed_at")),
        parse_timestamp(alert.get("dismissed_at")),
    ]
    state = alert.get("state")
    if state in {"fixed", "dismissed", "auto_dismissed"}:
        candidates.append(parse_timestamp(alert.get("updated_at")))
    candidates = [candidate for candidate in candidates if candidate is not None]
    if not candidates:
        return None
    return min(candidates)


def build_alert_history(alerts):
    grouped = {}
    for alert in alerts:
        repo = alert["repository"]["full_name"]
        key = (repo, advisory_key(alert))
        grouped.setdefault(key, []).append(
            {
                "created_at": parse_timestamp(alert["created_at"]),
                "closed_at": closure_timestamp(alert),
                "severity": advisory_severity(alert),
            }
        )
    return grouped


def median_age_days(ages_sorted):
    count = len(ages_sorted)
    midpoint = count // 2
    if count % 2 == 1:
        return math.floor(ages_sorted[midpoint])
    return math.floor((ages_sorted[midpoint - 1] + ages_sorted[midpoint]) / 2)


def compute_alert_summary(findings):
    ages = [finding["age_days"] for finding in findings]
    ages_sorted = sorted(ages)
    count = len(ages)

    return {
        "open_count": count,
        "avg_open_age_days": math.floor(sum(ages) / count),
        "p50_open_age_days": median_age_days(ages_sorted),
        "max_open_age_days": math.floor(max(ages)),
        "pct_open_over_30d": math.floor(sum(1 for age in ages if age >= 30) / count * 100),
        "pct_open_over_90d": math.floor(sum(1 for age in ages if age >= 90) / count * 100),
        "open_critical_count": sum(1 for finding in findings if finding["severity"] == "critical"),
        "open_critical_over_30d_count": sum(
            1
            for finding in findings
            if finding["severity"] == "critical" and finding["age_days"] >= 30
        ),
        "open_high_count": sum(1 for finding in findings if finding["severity"] == "high"),
        "open_high_over_60d_count": sum(
            1
            for finding in findings
            if finding["severity"] == "high" and finding["age_days"] >= 60
        ),
        "open_medium_count": sum(1 for finding in findings if finding["severity"] == "medium"),
        "open_medium_over_90d_count": sum(
            1
            for finding in findings
            if finding["severity"] == "medium" and finding["age_days"] >= 90
        ),
        "open_low_count": sum(1 for finding in findings if finding["severity"] == "low"),
        "open_unknown_count": sum(1 for finding in findings if finding["severity"] == ""),
    }


def build_current_alert_stats(alerts, now):
    repo_findings = {}

    for (repo, _), record in deduplicate_open_alerts(alerts).items():
        age_days = (now - record["created_at"]).total_seconds() / 86400
        repo_findings.setdefault(repo, []).append({"age_days": age_days, "severity": record["severity"]})

    return {
        repo: compute_alert_summary(findings)
        for repo, findings in repo_findings.items()
    }


def empty_current_alert_stats():
    return {
        "open_count": 0,
        "avg_open_age_days": "",
        "p50_open_age_days": "",
        "max_open_age_days": "",
        "pct_open_over_30d": 0,
        "pct_open_over_90d": 0,
        "open_critical_count": 0,
        "open_critical_over_30d_count": 0,
        "open_high_count": 0,
        "open_high_over_60d_count": 0,
        "open_medium_count": 0,
        "open_medium_over_90d_count": 0,
        "open_low_count": 0,
        "open_unknown_count": 0,
    }


def empty_history_stats():
    return {
        "open_count": 0,
        "open_critical_count": 0,
        "open_critical_over_30d_count": 0,
        "open_high_count": 0,
        "open_high_over_60d_count": 0,
        "open_medium_count": 0,
        "open_medium_over_90d_count": 0,
        "open_low_count": 0,
        "open_unknown_count": 0,
    }


def to_history_stats(summary):
    return {field: summary[field] for field in HISTORY_REPORT_FIELDNAMES if field not in {"scope", "snapshot_date"}}


def sort_key(row):
    max_open_age_days = row["max_open_age_days"] if row["max_open_age_days"] != "" else -1
    return (
        -row["open_critical_over_30d_count"],
        -row["open_critical_count"],
        -row["open_high_over_60d_count"],
        -row["open_high_count"],
        -row["pct_open_over_90d"],
        -max_open_age_days,
        -row["open_count"],
        row["repository"],
    )


def build_current_rows(repos, alert_stats):
    rows = []
    for repo in repos:
        repo_name = repo["full_name"]
        commit_info = repo["commit_info"]
        row = {
            "repository": repo_name,
            "has_dependabot_config": repo["has_dependabot_config"],
            "language": repo.get("language") or "",
            "size_kb": repo.get("size", 0),
            "created_at": repo.get("created_at", ""),
            "pushed_at": repo.get("pushed_at", ""),
            "last_commit_date": commit_info["last_commit_date"],
            "last_commit_author": commit_info["last_commit_author"],
        }
        row.update(alert_stats.get(repo_name, empty_current_alert_stats()))
        rows.append(row)

    rows.sort(key=sort_key)
    return rows


def enrich_repo(repo, total_repos, counter, lock):
    name = repo["full_name"]
    enriched = dict(repo)
    enriched["has_dependabot_config"] = has_dependabot_config(name)
    enriched["commit_info"] = get_last_commit(name)

    with lock:
        counter["done"] += 1
        print(f"  [{counter['done']}/{total_repos}] {name}", file=sys.stderr)

    return enriched


def snapshot_datetime(snapshot_date):
    return datetime.combine(snapshot_date, time.max, tzinfo=timezone.utc)


def build_weekly_history_rows(scope_name, alert_history, end_date, weeks):
    rows = []
    for offset in range(weeks):
        current_date = end_date - timedelta(weeks=offset)
        snapshot_at = snapshot_datetime(current_date)
        findings = []

        for instances in alert_history.values():
            active_instances = [
                instance
                for instance in instances
                if instance["created_at"] <= snapshot_at
                and (instance["closed_at"] is None or instance["closed_at"] > snapshot_at)
            ]
            if not active_instances:
                continue

            created_at = min(instance["created_at"] for instance in active_instances)
            severity = max(
                (instance["severity"] for instance in active_instances),
                key=lambda level: SEVERITY_RANK.get(level, 0),
                default="",
            )
            age_days = (snapshot_at - created_at).total_seconds() / 86400
            findings.append({"age_days": age_days, "severity": severity})

        row = {
            "scope": scope_name,
            "snapshot_date": current_date.isoformat(),
        }
        if findings:
            row.update(to_history_stats(compute_alert_summary(findings)))
        else:
            row.update(empty_history_stats())
        rows.append(row)

    rows.sort(key=lambda row: row["snapshot_date"])
    return rows


def parse_history_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise RuntimeError(f"Invalid --history-date '{value}'. Use YYYY-MM-DD.") from error


def print_csv(fieldnames, rows):
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


def build_current_report(scope_info):
    now = datetime.now(timezone.utc)

    if scope_info["kind"] == "org":
        print(f"Fetching repos for {scope_info['org']}...", file=sys.stderr)
        repos = fetch_repos(scope_info["org"])
        print(
            f"Checking {len(repos)} repos for dependabot config and commit metadata...",
            file=sys.stderr,
        )

        counter = {"done": 0}
        lock = threading.Lock()
        enriched_repos = []

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(enrich_repo, repo, len(repos), counter, lock) for repo in repos]
            for future in as_completed(futures):
                enriched_repos.append(future.result())

        enriched_repos.sort(key=lambda repo: repo["full_name"])
    else:
        print(f"Fetching repo metadata for {scope_info['repo']}...", file=sys.stderr)
        repo = fetch_repo(scope_info["repo"])
        print(f"Checking dependabot config and commit metadata for {scope_info['repo']}...", file=sys.stderr)
        enriched_repos = [
            {
                **repo,
                "has_dependabot_config": has_dependabot_config(scope_info["repo"]),
                "commit_info": get_last_commit(scope_info["repo"]),
            }
        ]

    print(f"Fetching open Dependabot alerts for {scope_info['name']}...", file=sys.stderr)
    alert_stats = build_current_alert_stats(fetch_open_alerts(scope_info), now)
    rows = build_current_rows(enriched_repos, alert_stats)

    total = len(rows)
    configured = sum(1 for row in rows if row["has_dependabot_config"])
    repos_with_alerts = sum(1 for row in rows if row["open_count"] > 0)
    repos_with_critical = sum(1 for row in rows if row["open_critical_count"] > 0)

    if total == 0:
        print(
            "\nSummary: 0/0 repos configured (0%), 0 repos with open alerts, 0 repos with open critical alerts",
            file=sys.stderr,
        )
    else:
        print(
            f"\nSummary: {configured}/{total} repos configured "
            f"({configured * 100 // total}%), "
            f"{repos_with_alerts} repos with open alerts, "
            f"{repos_with_critical} repos with open critical alerts",
            file=sys.stderr,
        )

    print_csv(CURRENT_REPORT_FIELDNAMES, rows)


def build_historical_report(scope_info, history_date, weeks):
    print(
        f"Fetching Dependabot alert history for {scope_info['name']} through {history_date.isoformat()}...",
        file=sys.stderr,
    )
    alert_history = build_alert_history(fetch_historical_alerts(scope_info))
    rows = build_weekly_history_rows(scope_info["name"], alert_history, history_date, weeks)
    print(
        f"\nSummary: generated {len(rows)} weekly snapshots for {scope_info['name']} "
        f"ending on {history_date.isoformat()}",
        file=sys.stderr,
    )
    print_csv(HISTORY_REPORT_FIELDNAMES, rows)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a current Dependabot health report or a weekly historical severity summary "
            "for a GitHub org or repo."
        )
    )
    parser.add_argument("scope", help="GitHub org name like 'foo' or repo name like 'foo/bar'")
    parser.add_argument(
        "--history-date",
        help="Anchor date for weekly historical output in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        help="Number of weekly snapshots to emit when using --history-date",
    )
    args = parser.parse_args()

    scope_info = parse_scope(args.scope)

    if (args.history_date is None) != (args.weeks is None):
        raise RuntimeError("Use --history-date and --weeks together.")

    if args.weeks is not None and args.weeks <= 0:
        raise RuntimeError("--weeks must be a positive integer.")

    if args.history_date is not None:
        build_historical_report(scope_info, parse_history_date(args.history_date), args.weeks)
    else:
        build_current_report(scope_info)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
