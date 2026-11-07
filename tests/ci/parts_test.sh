#!/usr/bin/env bash
# Tests .github/ci/parts.sh in a scratch tree with fake cargo, npm and curl
# first on PATH. They log their arguments to $FAKE_LOG; cargo and npm fail
# when "<tool> <subcommand>" equals $FAKE_FAIL.
# Run: bash tests/ci/parts_test.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
script="$root/.github/ci/parts.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/bin" "$work/tree/.github/ci" "$work/tree/.github/ciod" \
  "$work/tree/tests/ci" "$work/tree/target/debug"
for tool in cargo npm; do
  cat > "$work/bin/$tool" <<FAKE
#!/usr/bin/env bash
printf '%s\n' "$tool \$*" >> "\$FAKE_LOG"
[ "$tool \$1" != "\${FAKE_FAIL:-}" ]
FAKE
done
printf '#!/usr/bin/env bash\nexit 0\n' > "$work/bin/curl"
printf '#!/usr/bin/env bash\nexec sleep 30\n' > "$work/tree/target/debug/ip-info"
echo 'echo generated ok' > "$work/tree/.github/ci/generated.sh"
echo 'echo "prefetch $*"' > "$work/tree/.github/ciod/prefetch.sh"
echo 'exit "${FAKE_CI_SCRIPT_RC:-0}"' > "$work/tree/tests/ci/one_test.sh"
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
    GITHUB_STEP_SUMMARY="$work/summary" bash "$script" 2>&1) || status=$?
  summary=$(cat "$work/summary")
  log=$(cat "$FAKE_LOG")
}

# A pull request where every part passes: slow tests are filtered out.
run true pull_request
[ "$status" = 0 ] || fail "all pass: exit $status ($out)"
for name in fmt clippy generated ci-scripts npm build rust-tests browser; do
  grep -q "^| $name | passed | [0-9]* |$" <<< "$summary" || fail "all pass: $name not passed: $summary"
done
grep -qx "cargo clippy --locked --all-targets --target-dir target/clippy -- -D warnings" <<< "$log" ||
  fail "all pass: clippy command: $log"
grep -qx "cargo nextest run --locked --profile ci -E not test(/^slow_|::slow_/)" <<< "$log" ||
  fail "all pass: nextest filter: $log"
grep -qx "cargo test --locked --doc" <<< "$log" || fail "all pass: doc tests: $log"
grep -qx "npm run test:browser -- --grep-invert @db|@slow" <<< "$log" || fail "all pass: browser filter: $log"
[ -s "$work/temp/parts/build.time" ] || fail "all pass: no build.time"

# A scheduled run includes slow tests.
run true schedule
[ "$status" = 0 ] || fail "schedule: exit $status ($out)"
grep -qx "cargo nextest run --locked --profile ci" <<< "$log" || fail "schedule: nextest command: $log"
grep -qx "npm run test:browser -- --grep-invert @db" <<< "$log" || fail "schedule: browser filter: $log"

# A build error: the tests and the browser do not run, and the run fails.
FAKE_FAIL="cargo build" run true schedule
[ "$status" = 1 ] || fail "build fails: exit $status"
grep -q "^| build | failed: exit 1 |" <<< "$summary" || fail "build fails: build row: $summary"
grep -q "^| rust-tests | failed: exit 1 |" <<< "$summary" || fail "build fails: rust-tests row: $summary"
grep -q "^| browser | failed: exit 1 |" <<< "$summary" || fail "build fails: browser row: $summary"
grep -q "not run: build failed" <<< "$out" || fail "build fails: reason missing: $out"
grep -q "^cargo nextest\|^npm run" <<< "$log" && fail "build fails: tests ran: $log"
grep -q "::error::part fmt" <<< "$out" && fail "build fails: fmt reported: $out"

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
