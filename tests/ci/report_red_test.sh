#!/usr/bin/env bash
# Tests .github/ci/report-red.sh against a fake gh first on PATH, which logs
# its arguments and answers `issue list` with $FAKE_LIST.
# Run: bash tests/ci/report_red_test.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
script="$root/.github/ci/report-red.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir "$work/bin"
cat > "$work/bin/gh" <<'GH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
[ -z "${FAKE_FAIL:-}" ] || { echo "gh: HTTP 502" >&2; exit 1; }
case "$1 $2" in
  "issue list") printf '%s\n' "$FAKE_LIST" ;;
  "issue create") echo "https://github.com/o/r/issues/9" ;;
  *) echo "unexpected: $*" >&2; exit 2 ;;
esac
GH
chmod +x "$work/bin/gh"

export PATH="$work/bin:$PATH" FAKE_LOG="$work/log"
export GITHUB_REPOSITORY=o/r GITHUB_SERVER_URL=https://github.com GITHUB_RUN_ID=42
export GITHUB_SHA=0123456789abcdef0123456789abcdef01234567
title="Nightly dependency audit failed"
failures=0

fail() { echo "FAIL: $1"; failures=$((failures + 1)); }

# Runs the script with FAKE_LIST=$1 (and FAKE_FAIL if set); sets $status, $out, $log.
run() {
  : > "$FAKE_LOG"
  status=0
  out=$(FAKE_LIST=$1 bash "$script" "$title" 2>&1) || status=$?
  log=$(cat "$FAKE_LOG")
}

# No open issue with the title, only a longer one: one create, with the run URL.
run '[{"number":3,"title":"Nightly dependency audit failed again"}]'
[ "$status" = 0 ] || fail "no issue: exit $status ($out)"
[ "$(grep -c '^issue create' <<< "$log")" = 1 ] || fail "no issue: expected one create, log: $log"
create=$(grep '^issue create' <<< "$log" || true)
[[ $create == *"--title $title --body"* ]] || fail "no issue: title missing: $create"
[[ $create == *"https://github.com/o/r/actions/runs/42 failed on 0123456"* ]] || fail "no issue: run URL missing: $create"
grep -q 'comment\|label' <<< "$log" && fail "no issue: comment or label: $log"
[[ $out == *"https://github.com/o/r/issues/9"* ]] || fail "no issue: URL not printed: $out"

# An open issue with exactly the title: nothing created or commented.
run '[{"number":3,"title":"Nightly dependency audit failed again"},{"number":7,"title":"Nightly dependency audit failed"}]'
[ "$status" = 0 ] || fail "open issue: exit $status ($out)"
[ "$(grep -vc '^issue list' <<< "$log")" = 0 ] || fail "open issue: expected only the list, log: $log"
[[ $out == *"already open: #7"* ]] || fail "open issue: output: $out"

# gh fails: the script fails.
FAKE_FAIL=1 run '[]'
[ "$status" != 0 ] || fail "gh fails: exit 0 ($out)"
grep -q '^issue create' <<< "$log" && fail "gh fails: created anyway: $log"

if [ "$failures" != 0 ]; then
  echo "$failures failure(s)"
  exit 1
fi
echo "report_red_test: all passed"
