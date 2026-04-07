#!/usr/bin/env python3

import argparse
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


def paginate(endpoint):
    """Fetch all pages from a GitHub API endpoint returning JSON arrays."""
    result = subprocess.run(
        [
            "gh", "api",
            "--method", "GET",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10",
            endpoint,
            "--paginate",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error fetching {endpoint}: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    items = []
    decoder = json.JSONDecoder()
    text = result.stdout.strip()
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


def gh_api(endpoint):
    """Call a single GitHub API endpoint, return (success, parsed_json)."""
    result = subprocess.run(
        [
            "gh", "api",
            "--method", "GET",
            "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10",
            endpoint,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, None
    return True, json.loads(result.stdout)


def has_dependabot_config(repo_full_name):
    """Check if a repo has .github/dependabot.yml or .github/dependabot.yaml."""
    for filename in ("dependabot.yml", "dependabot.yaml"):
        ok, _ = gh_api(f"/repos/{repo_full_name}/contents/.github/{filename}")
        if ok:
            return True
    return False


def get_last_commit(repo_full_name):
    """Get the last commit's date and committer login on the default branch."""
    ok, data = gh_api(f"/repos/{repo_full_name}/commits?per_page=1")
    if ok and data:
        commit = data[0]
        return {
            "last_commit_date": commit["commit"]["committer"]["date"],
            "last_commit_author": (commit.get("author") or {}).get("login", ""),
        }
    return {"last_commit_date": "", "last_commit_author": ""}


def main():
    parser = argparse.ArgumentParser(
        description="Check which repos in a GitHub org have Dependabot configured."
    )
    parser.add_argument("org", help="GitHub organization name")
    args = parser.parse_args()

    print(f"Fetching repos for {args.org}...", file=sys.stderr)
    repos = paginate(f"/orgs/{args.org}/repos?type=sources&per_page=100")

    # Filter out archived and empty repos
    repos = [r for r in repos if not r["archived"] and r.get("size", 0) > 0]
    repos.sort(key=lambda r: r["full_name"])

    print(f"Checking {len(repos)} repos for dependabot config...", file=sys.stderr)

    results = {}
    lock = threading.Lock()
    done = 0

    # Index repos by full_name for metadata lookup
    repo_by_name = {r["full_name"]: r for r in repos}

    def check(repo):
        nonlocal done
        name = repo["full_name"]
        configured = has_dependabot_config(name)
        commit_info = get_last_commit(name)
        with lock:
            done += 1
            print(f"  [{done}/{len(repos)}] {name}", file=sys.stderr)
        return name, configured, commit_info

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(check, r): r for r in repos}
        for future in as_completed(futures):
            name, configured, commit_info = future.result()
            results[name] = (configured, commit_info)

    rows = []
    for name in sorted(results):
        configured, commit_info = results[name]
        r = repo_by_name[name]
        rows.append({
            "repository": name,
            "has_dependabot_config": configured,
            "language": r.get("language") or "",
            "size_kb": r.get("size", 0),
            "created_at": r.get("created_at", ""),
            "pushed_at": r.get("pushed_at", ""),
            "last_commit_date": commit_info["last_commit_date"],
            "last_commit_author": commit_info["last_commit_author"],
        })

    # Summary to stderr
    total = len(rows)
    configured = sum(1 for r in rows if r["has_dependabot_config"])
    unconfigured = total - configured
    if total == 0:
        print("\nSummary: 0/0 repos configured (0%), 0 unconfigured (0%)", file=sys.stderr)
    else:
        print(f"\nSummary: {configured}/{total} repos configured "
              f"({configured * 100 // total}%), "
              f"{unconfigured} unconfigured ({unconfigured * 100 // total}%)",
              file=sys.stderr)

    # CSV to stdout
    fieldnames = [
        "repository",
        "has_dependabot_config",
        "language",
        "size_kb",
        "created_at",
        "pushed_at",
        "last_commit_date",
        "last_commit_author",
    ]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
