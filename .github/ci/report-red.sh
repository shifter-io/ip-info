#!/usr/bin/env bash
# Usage: report-red.sh TITLE
#
# Opens one issue named TITLE for a red scheduled run, unless an open issue
# has exactly that title already; then it only prints its number (Maestro: no
# bot comments on issues). Needs gh with GH_TOKEN, python3 and the Actions
# variables GITHUB_REPOSITORY, GITHUB_SERVER_URL, GITHUB_RUN_ID, GITHUB_SHA.
set -euo pipefail
TITLE=${1:?usage: report-red.sh TITLE}
: "${GITHUB_REPOSITORY:?}" "${GITHUB_SERVER_URL:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_SHA:?}"

# The search matches words anywhere in a title, so keep only the exact title.
open=$(gh issue list -R "$GITHUB_REPOSITORY" --state open --limit 100 \
    --search "in:title $TITLE" --json number,title |
  TITLE="$TITLE" python3 -c '
import json, os, sys
print(next((str(i["number"]) for i in json.load(sys.stdin) if i["title"] == os.environ["TITLE"]), ""))')
if [ -n "$open" ]; then
  echo "already open: #$open"
  exit 0
fi

run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
body="$run_url failed on ${GITHUB_SHA:0:7}. The run's job summary lists the failed parts. This never blocks pull requests."
url=$(gh issue create -R "$GITHUB_REPOSITORY" --title "$TITLE" --body "$body")
echo "opened: $url"
