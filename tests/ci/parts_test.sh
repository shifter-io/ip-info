#!/usr/bin/env bash
# Tests .github/ci/parts.sh in a scratch tree with fake cargo, npm, curl and
# diff-cover first on PATH, and a fake server and scripts/smoke.py in the
# tree. They log their arguments to $FAKE_LOG (the server its MMDB_PATH and
# BIND_ADDR), and cargo adds " (instrumented)" once `cargo llvm-cov show-env`
# set its variables; cargo and npm fail when "<tool> <subcommand>" equals
# $FAKE_FAIL, and smoke exits with $FAKE_SMOKE_RC.
# Run: bash tests/ci/parts_test.sh
set -euo pipefail
# From a shell that sourced `cargo llvm-cov show-env`: the fakes decide.
unset CARGO_LLVM_COV
root=$(cd "$(dirname "$0")/../.." && pwd)
script="$root/.github/ci/parts.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/bin" "$work/tree/.github/ci" "$work/tree/.github/ciod" \
  "$work/tree/tests/ci" "$work/tree/target/debug" "$work/tree/scripts"
cat > "$work/bin/npm" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "npm $*" >> "$FAKE_LOG"
[ "npm $1" != "${FAKE_FAIL:-}" ]
FAKE
cat > "$work/bin/cargo" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "cargo $*${CARGO_LLVM_COV:+ (instrumented)}" >> "$FAKE_LOG"
[ "$1 $2" != "llvm-cov show-env" ] || [ -n "${FAKE_NO_COV:-}" ] || echo "export CARGO_LLVM_COV=1"
[ "cargo $1" != "${FAKE_FAIL:-}" ]
FAKE
# The last argument is the Markdown report's path.
cat > "$work/bin/diff-cover" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "diff-cover $*" >> "$FAKE_LOG"
echo "fake diff-cover report" > "${*: -1}"
exit "${FAKE_DIFF_COVER_RC:-0}"
FAKE
printf '#!/usr/bin/env bash\nexit 0\n' > "$work/bin/curl"
cat > "$work/tree/target/debug/ip-info" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "server MMDB_PATH=$MMDB_PATH BIND_ADDR=$BIND_ADDR" >> "$FAKE_LOG"
exec sleep 30
FAKE
cat > "$work/tree/scripts/smoke.py" <<'FAKE'
import os, sys
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(' '.join(['smoke', *sys.argv[1:]]) + '\n')
sys.exit(int(os.environ.get('FAKE_SMOKE_RC', '0')))
FAKE
echo 'echo generated ok' > "$work/tree/.github/ci/generated.sh"
echo 'echo "prefetch $*"' > "$work/tree/.github/ciod/prefetch.sh"
echo 'exit "${FAKE_CI_SCRIPT_RC:-0}"' > "$work/tree/tests/ci/one_test.sh"
printf 'import unittest\n\nclass One(unittest.TestCase):\n    def test_one(self):\n        pass\n' \
  > "$work/tree/tests/ci/test_one.py"
chmod +x "$work/bin/"* "$work/tree/target/debug/ip-info"

export PATH="$work/bin:$PATH" FAKE_LOG="$work/log"
failures=0

# The inner runs' output holds workflow commands (::error::, ::group::);
# broken up, they print as text instead of acting on this job.
fail() {
  echo "FAIL: ${1//::/: :}"
  failures=$((failures + 1))
}

# run CODE EVENT: runs parts.sh in the scratch tree; sets $status, $out,
# $summary and $log.
run() {
  rm -rf "$work/temp"
  mkdir "$work/temp"
  : > "$FAKE_LOG"
  : > "$work/summary"
  status=0
  out=$(cd "$work/tree" && code=$1 GITHUB_EVENT_NAME=$2 RUNNER_TEMP="$work/temp" \
    GITHUB_STEP_SUMMARY="$work/summary" DIFF_COVER="$work/bin/diff-cover" bash "$script" 2>&1) || status=$?
  summary=$(cat "$work/summary")
  log=$(cat "$FAKE_LOG")
}

# A pull request where every part passes: slow tests are filtered out, the
# build and the tests run instrumented, clippy and fmt do not, the server runs
# on the test database, smoke runs after Playwright against the server, and
# the per-file table and the changed-line report are in the summary.
run true pull_request
[ "$status" = 0 ] || fail "all pass: exit $status ($out)"
for name in fmt clippy generated ci-scripts npm build rust-tests browser coverage; do
  grep -q "^| $name | passed |$" <<< "$summary" || fail "all pass: $name not passed: $summary"
done
grep -qx "cargo clippy --locked --all-targets --target-dir target/clippy -- -D warnings" <<< "$log" ||
  fail "all pass: clippy command: $log"
grep -qx "cargo fmt --check" <<< "$log" || fail "all pass: fmt command: $log"
for line in "llvm-cov clean --workspace" "build --locked --bin ip-info" \
  "nextest run --locked --profile ci -E not test(/^slow_|::slow_/)" "test --locked --doc" \
  "llvm-cov report --lcov --output-path $work/temp/parts/lcov.info" "llvm-cov report --summary-only"; do
  grep -qxF "cargo $line (instrumented)" <<< "$log" || fail "all pass: not instrumented: $line: $log"
done
grep -qxF "diff-cover $work/temp/parts/lcov.info --compare-branch=HEAD^1 --fail-under=85 --markdown-report $work/temp/parts/diff-cover.md" <<< "$log" ||
  fail "all pass: diff-cover command: $log"
grep -qx "fake diff-cover report" <<< "$summary" || fail "all pass: no coverage report: $summary"
grep -q "^== server log (exit status [0-9]*)$" <<< "$out" || fail "all pass: server not stopped: $out"
grep -qx "npm run test:browser -- --grep-invert @slow" <<< "$log" || fail "all pass: browser filter: $log"
grep -qx "server MMDB_PATH=$work/tree/tests/fixtures/ip-info-test.mmdb BIND_ADDR=127.0.0.1:[0-9]*" <<< "$log" ||
  fail "all pass: server database: $log"
port=$(sed -n 's/^server .* BIND_ADDR=127.0.0.1:\([0-9]*\)$/\1/p' <<< "$log")
# Other parts log at the same time: compare line numbers, not neighbours.
playwright_at=$(grep -n '^npm run test:browser' <<< "$log" | cut -d: -f1)
smoke_at=$(grep -nx "smoke http://127.0.0.1:$port" <<< "$log" | cut -d: -f1)
[ -n "$port" ] && [ -n "$smoke_at" ] && [ "$smoke_at" -gt "${playwright_at:-0}" ] ||
  fail "all pass: smoke not after Playwright on the server's URL: $log"
[ "$(grep -c '^```$' <<< "$summary")" = 2 ] || fail "all pass: no per-file table: $summary"
[ -s "$work/temp/parts/build.time" ] || fail "all pass: no build.time"
grep -qx "[0-9][0-9]*" "$work/temp/parts/parts.start" || fail "all pass: no parts.start"

# A scheduled run includes slow tests.
run true schedule
[ "$status" = 0 ] || fail "schedule: exit $status ($out)"
grep -qx "cargo nextest run --locked --profile ci (instrumented)" <<< "$log" || fail "schedule: nextest command: $log"
grep -qx "npm run test:browser --" <<< "$log" || fail "schedule: browser filter: $log"
grep -q "^smoke " <<< "$log" || fail "schedule: no smoke: $log"
# No pull-request diff: the lcov report only, no changed-line rule.
grep -q "^| coverage | passed |" <<< "$summary" || fail "schedule: coverage row: $summary"
grep -q "llvm-cov report --lcov" <<< "$log" || fail "schedule: no lcov report: $log"
grep -q "llvm-cov report --summary-only" <<< "$log" || fail "schedule: no per-file table: $log"
grep -q "^diff-cover" <<< "$log" && fail "schedule: diff-cover ran: $log"

# Under 85% of the changed lines covered: coverage fails the run, and its
# report is still in the summary.
FAKE_DIFF_COVER_RC=1 run true pull_request
[ "$status" = 1 ] || fail "coverage fails: exit $status"
grep -q "^| coverage | failed: exit 1 |" <<< "$summary" || fail "coverage fails: row: $summary"
grep -qx "fake diff-cover report" <<< "$summary" || fail "coverage fails: no report: $summary"

# cargo-llvm-cov set nothing: no build, no tests, no coverage.
FAKE_NO_COV=1 run true pull_request
[ "$status" = 1 ] || fail "no show-env: exit $status"
grep -q "not run: cargo llvm-cov show-env failed" <<< "$out" || fail "no show-env: reason missing: $out"
grep -q "^cargo build" <<< "$log" && fail "no show-env: build ran: $log"
grep -q "^| coverage | failed: exit 1 |" <<< "$summary" || fail "no show-env: coverage row: $summary"

# A build error: the tests and the browser do not run, and the run fails.
FAKE_FAIL="cargo build" run true schedule
[ "$status" = 1 ] || fail "build fails: exit $status"
grep -q "^| build | failed: exit 1 |" <<< "$summary" || fail "build fails: build row: $summary"
grep -q "^| rust-tests | failed: exit 1 |" <<< "$summary" || fail "build fails: rust-tests row: $summary"
grep -q "^| browser | failed: exit 1 |" <<< "$summary" || fail "build fails: browser row: $summary"
grep -q "^| coverage | failed: exit 1 |" <<< "$summary" || fail "build fails: coverage row: $summary"
grep -q "not run: build failed" <<< "$out" || fail "build fails: reason missing: $out"
grep -q "not run: rust-tests or browser failed" <<< "$out" || fail "build fails: coverage reason: $out"
grep -q "^cargo nextest\|^npm run" <<< "$log" && fail "build fails: tests ran: $log"
grep -q "::error::part fmt" <<< "$out" && fail "build fails: fmt reported: $out"

# A failing smoke check fails browser, and so coverage does not run.
FAKE_SMOKE_RC=1 run true pull_request
[ "$status" = 1 ] || fail "smoke fails: exit $status"
grep -q "^| browser | failed: exit 1 |" <<< "$summary" || fail "smoke fails: browser row: $summary"
grep -q "^| coverage | failed: exit 1 |" <<< "$summary" || fail "smoke fails: coverage row: $summary"

# A failing CI script fails its part and the run; the others still pass.
FAKE_CI_SCRIPT_RC=3 run true pull_request
[ "$status" = 1 ] || fail "ci script fails: exit $status"
grep -q "^| ci-scripts | failed: exit 3 |" <<< "$summary" || fail "ci script fails: row: $summary"
grep -q "^| browser | passed |" <<< "$summary" || fail "ci script fails: browser row: $summary"

# A docs-only change runs only generated and ci-scripts, and says why.
run false pull_request
[ "$status" = 0 ] || fail "docs only: exit $status ($out)"
[ -z "$log" ] || fail "docs only: cargo or npm ran: $log"
grep -q "^Docs-only change (rule: .github/ci/changes.sh)" <<< "$summary" || fail "docs only: note: $summary"
[ "$(grep -c '| passed |' <<< "$summary")" = 2 ] || fail "docs only: rows: $summary"

# A part whose shell is killed, and an expected part never started: both
# fail as "no result".
mkdir -p "$work/lib"
status=0
out=$(EV="$work/lib" GITHUB_STEP_SUMMARY="$work/lib/summary" PARTS_LIB=1 bash -c '
  . "$1"
  part ok true
  part killed bash -c "kill -9 \$PPID"
  collect ok killed absent' _ "$script" 2>&1) || status=$?
[ "$status" = 1 ] || fail "killed: exit $status ($out)"
grep -q "^| ok | passed |" "$work/lib/summary" || fail "killed: ok row: $(cat "$work/lib/summary")"
grep -q "^| killed | failed: no result (crashed or killed) |" "$work/lib/summary" ||
  fail "killed: killed row: $(cat "$work/lib/summary")"
grep -q "^| absent | failed: no result (crashed or killed) |" "$work/lib/summary" ||
  fail "killed: absent row: $(cat "$work/lib/summary")"

if [ "$failures" != 0 ]; then
  echo "$failures failure(s)"
  exit 1
fi
echo "parts_test: all passed"
