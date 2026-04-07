# TODO

## Findings To Fix

- [x] Guard against division by zero in `config-coverage.py` when an org has zero non-archived, non-empty repos, and make sure the script still emits a sensible summary/CSV.
- [x] Fix `p50_open_age_days` in `alert-age.py` so even-sized alert sets report a true median instead of the upper middle value.
- [ ] Stop treating every GitHub API failure in `config-coverage.py` as "no config" or "no commit metadata"; distinguish expected `404` results from permission, rate-limit, and transient failures.

## Follow-On Hardening

- [ ] Add a small test harness or fixture-based validation for the report calculations so we can change behavior with confidence.
- [ ] Factor shared `gh api` pagination/parsing code into a reusable helper to reduce duplication between scripts.
- [ ] Document failure modes and operational assumptions in `README.md`, especially the need for authenticated `gh` access and how API errors are surfaced.
- [ ] Add a `last_meaningful_dev_date` signal that skips bot commits and config/docs-only churn so repo activity reflects recent development work rather than the last default-branch commit of any kind.
