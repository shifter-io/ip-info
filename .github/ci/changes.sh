#!/usr/bin/env bash
# Prints code=true when the run must build and test, code=false for a pull
# request that changes only README.md, LICENSE or docs/. The `changes` job
# and `gate` both run it, so they cannot disagree on a docs-only change.
#
# Checkout makes HEAD the pull request merged into its base, so HEAD^1 is the
# base and the diff is the request's; it needs fetch-depth 2.
set -euo pipefail
if [ "${GITHUB_EVENT_NAME:-}" != pull_request ]; then
  echo code=true
  exit 0
fi
# --no-renames lists a moved file under its old path too.
files=$(git diff --name-only --no-renames HEAD^1 HEAD)
code=false
[ -n "$files" ] || code=true
grep -qvE '^(README\.md|LICENSE|docs/.+)$' <<< "$files" && code=true
echo "code=$code"
