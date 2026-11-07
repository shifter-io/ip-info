#!/usr/bin/env bash
# Runs the `tier1` job's checks (README.md, Development) as parts, at once
# where they do not wait for each other, and fails when any part failed.
#
# It writes $EV/parts.start (epoch seconds) first. Each part writes
# $EV/NAME.log (its output), $EV/NAME.time ("start end", epoch seconds) and,
# last, $EV/NAME.rc (its exit status). A part with no .rc file crashed or was
# killed and fails as "no result". .github/ci/timing.py reports the times.
#
# With code=true (.github/ci/changes.sh):
#   1. at once, in the background: fmt, clippy (own build folder, so it never
#      waits for the build's lock), generated, ci-scripts, npm (with
#      Playwright's browser);
#   2. build, the server binary, instrumented for coverage: from here on,
#      cargo runs rustc through cargo-llvm-cov (then sccache), which adds
#      -C instrument-coverage to this workspace's crates only;
#   3. then, in the background: rust-tests (nextest, then the doc tests);
#   4. once npm is done: browser, against the binary build made, stopped
#      with SIGTERM so it writes its coverage profile;
#   5. after both: coverage, the lcov report of all of them and, on pull
#      requests, diff-cover: under 85% of the changed lines covered fails.
#      Other events have no single diff to check.
# With code=false (a docs-only pull request): generated and ci-scripts only.
#
# On pull requests, tests marked slow are skipped: Rust tests named slow_*
# and Playwright tests tagged @slow (.github/ci/pins.env). Other events run
# them.
#
# Needs: code, RUNNER_TEMP, GITHUB_EVENT_NAME, GITHUB_STEP_SUMMARY, for
# generated MARKDOWN_PYTHON and, for coverage, cargo-llvm-cov and DIFF_COVER
# (default: diff-cover on PATH). Run: bash .github/ci/parts.sh
# The test (tests/ci/parts_test.sh) sources it with PARTS_LIB=1 and calls
# the functions below with its own commands.
set -euo pipefail
# shellcheck source=pins.env
. "$(dirname "${BASH_SOURCE[0]}")/pins.env"

declare -A pids=()

# part NAME CMD...: runs CMD in the background as part NAME.
part() {
  local name=$1
  shift
  (
    start=$(date +%s)
    # CMD runs as its own job, so `set -e` holds inside it even when CMD is a
    # function: a function called on the left of || would ignore it.
    "$@" > "$EV/$name.log" 2>&1 &
    rc=0
    wait "$!" || rc=$?
    echo "$start $(date +%s)" > "$EV/$name.time"
    echo "$rc" > "$EV/$name.rc.tmp"
    mv "$EV/$name.rc.tmp" "$EV/$name.rc"
  ) &
  pids[$name]=$!
}

# passed NAME: waits for part NAME; true when it wrote exit status 0.
passed() {
  local status=0
  wait "${pids[$1]}" || status=$?
  [ "$status" = 0 ] && [ -f "$EV/$1.rc" ] && [ "$(< "$EV/$1.rc")" = 0 ]
}

# not_run REASON: the command of a part whose inputs failed.
not_run() {
  echo "not run: $1"
  return 1
}

slow_skipped() { [ "${GITHUB_EVENT_NAME:-}" = pull_request ]; }

ci_scripts() {
  local test
  for test in tests/ci/*.sh; do
    echo "== $test"
    bash "$test"
  done
  echo "== tests/ci/test_*.py"
  python3 -m unittest discover -s tests/ci -p 'test_*.py'
}

# The packages, then Playwright's headless shell, which needs them: it was
# prefetched into the image, or is installed now.
npm_install() {
  npm ci
  bash .github/ciod/prefetch.sh playwright
}

instrumented_build() {
  cargo llvm-cov clean --workspace
  cargo build --locked --bin ip-info
}

rust_tests() {
  local filter=()
  slow_skipped && filter=(-E "not test(/$SLOW_RUST_FILTER/)")
  cargo nextest run --locked --profile ci "${filter[@]}"
  # nextest does not run doc tests.
  cargo test --locked --doc
}

# stop_server PID: SIGTERM; the server exits by itself and writes its
# coverage profile as it exits. It runs in an EXIT trap, where a failed
# command would change the exit status, so none fails.
stop_server() {
  local status=0
  kill "$1" 2> /dev/null || :
  wait "$1" || status=$?
  echo "== server log (exit status $status)"
  cat "$RUNNER_TEMP/server.log"
}

# Starts the binary build made on a free port: Playwright's own web server
# would bind 8080 and reuse any server already listening there.
browser() {
  local port server grep=@db
  slow_skipped && grep="@db|$SLOW_BROWSER_TAG"
  port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  BIND_ADDR="127.0.0.1:$port" target/debug/ip-info > "$RUNNER_TEMP/server.log" 2>&1 &
  server=$!
  trap 'stop_server "$server"' EXIT
  for _ in $(seq 60); do
    curl -fsS "http://127.0.0.1:$port/healthz" > /dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "http://127.0.0.1:$port/healthz" > /dev/null
  TEST_BASE_URL="http://127.0.0.1:$port" npm run test:browser -- --grep-invert "$grep"
}

# The changed-line rule: diff-cover's exit status is the part's result.
coverage() {
  local rc=0
  cargo llvm-cov report --lcov --output-path "$EV/lcov.info"
  if [ "${GITHUB_EVENT_NAME:-}" != pull_request ]; then
    echo "$EV/lcov.info written; the changed-line rule applies to pull requests only"
    return 0
  fi
  "${DIFF_COVER:-diff-cover}" "$EV/lcov.info" --compare-branch=HEAD^1 --fail-under=85 \
    --markdown-report "$EV/diff-cover.md" || rc=$?
  [ ! -f "$EV/diff-cover.md" ] || cat "$EV/diff-cover.md" >> "$GITHUB_STEP_SUMMARY"
  return "$rc"
}

run_code() {
  part fmt cargo fmt --check
  part clippy cargo clippy --locked --all-targets --target-dir target/clippy -- -D warnings
  part generated bash .github/ci/generated.sh
  part ci-scripts ci_scripts
  part npm npm_install
  # From here on, cargo builds instrumented; the parts above keep their builds.
  # shellcheck source=/dev/null
  source <(cargo llvm-cov show-env --sh)
  if [ "${CARGO_LLVM_COV:-}" = 1 ]; then
    part build instrumented_build
  else
    part build not_run "cargo llvm-cov show-env failed"
  fi
  local built=false
  if passed build; then
    built=true
    part rust-tests rust_tests
  else
    part rust-tests not_run "build failed"
  fi
  if passed npm && [ "$built" = true ]; then
    part browser browser
  else
    part browser not_run "build or npm failed"
  fi
  if passed rust-tests && passed browser; then
    part coverage coverage
  else
    part coverage not_run "rust-tests or browser failed"
  fi
}

run_docs() {
  local note="Docs-only change (rule: .github/ci/changes.sh): format, lint, build, Rust and browser parts not needed."
  echo "$note"
  echo "$note" >> "$GITHUB_STEP_SUMMARY"
  part generated bash .github/ci/generated.sh
  part ci-scripts ci_scripts
}

# collect NAME...: waits for every part, then checks the named ones (a fixed
# list, never the .rc files that happen to exist). Prints each log, adds a
# table of results to the job summary (timing.py adds the times), and fails
# when any named part failed.
collect() {
  local name rc result failed=0
  wait
  echo "| Part | Result |" >> "$GITHUB_STEP_SUMMARY"
  echo "|---|---|" >> "$GITHUB_STEP_SUMMARY"
  for name in "$@"; do
    rc=
    [ -f "$EV/$name.rc" ] && rc=$(< "$EV/$name.rc")
    [ -n "$rc" ] || rc=missing
    case "$rc" in
      0) result=passed ;;
      missing) result="failed: no result (crashed or killed)" ;;
      *) result="failed: exit $rc" ;;
    esac
    echo "| $name | $result |" >> "$GITHUB_STEP_SUMMARY"
    echo "::group::$name: $result"
    [ -f "$EV/$name.log" ] && cat "$EV/$name.log"
    echo "::endgroup::"
    if [ "$rc" != 0 ]; then
      echo "::error::part $name $result"
      failed=$((failed + 1))
    fi
  done
  [ "$failed" = 0 ]
}

main() {
  : "${code:?is not set; run .github/ci/changes.sh first}" "${RUNNER_TEMP:?}" "${GITHUB_STEP_SUMMARY:?}"
  EV="$RUNNER_TEMP/parts"
  mkdir -p "$EV"
  date +%s > "$EV/parts.start"
  if [ "$code" = true ]; then
    run_code
    collect fmt clippy generated ci-scripts npm build rust-tests browser coverage
  else
    run_docs
    collect generated ci-scripts
  fi
}

[ -n "${PARTS_LIB:-}" ] || main
