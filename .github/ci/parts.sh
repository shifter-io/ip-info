#!/usr/bin/env bash
# Runs the `tier1` job's checks (README.md, Development) as parts, at once
# where they do not wait for each other, and fails when any part failed.
#
# Each part writes $EV/NAME.log (its output), $EV/NAME.time ("start end",
# epoch seconds) and, last, $EV/NAME.rc (its exit status). A part with no
# .rc file crashed or was killed and fails as "no result".
#
# With code=true (.github/ci/changes.sh):
#   1. at once, in the background: fmt, clippy (own build folder, so it never
#      waits for the build's lock), generated, ci-scripts, npm (with
#      Playwright's browser);
#   2. build, the server binary;
#   3. then, in the background: rust-tests (nextest, then the doc tests);
#   4. once npm is done: browser, against the binary build made.
# With code=false (a docs-only pull request): generated and ci-scripts only.
#
# On pull requests, tests marked slow are skipped: Rust tests named slow_*
# and Playwright tests tagged @slow. Other events run them.
#
# Needs: code, RUNNER_TEMP, GITHUB_EVENT_NAME, GITHUB_STEP_SUMMARY and, for
# generated, MARKDOWN_PYTHON. Run: bash .github/ci/parts.sh
# The test (tests/ci/parts_test.sh) sources it with PARTS_LIB=1 and calls
# the functions below with its own commands.
set -euo pipefail

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
}

# The packages, then Playwright's headless shell, which needs them: it was
# prefetched into the image, or is installed now.
npm_install() {
  npm ci
  bash .github/ciod/prefetch.sh playwright
}

rust_tests() {
  local filter=()
  slow_skipped && filter=(-E 'not test(/^slow_|::slow_/)')
  cargo nextest run --locked --profile ci "${filter[@]}"
  # nextest does not run doc tests.
  cargo test --locked --doc
}

# Starts the binary build made on a free port: Playwright's own web server
# would bind 8080 and reuse any server already listening there.
browser() {
  local port server grep=@db
  slow_skipped && grep="@db|@slow"
  port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  BIND_ADDR="127.0.0.1:$port" target/debug/ip-info > "$RUNNER_TEMP/server.log" 2>&1 &
  server=$!
  # An EXIT trap does not change the exit status.
  trap 'kill "$server" 2> /dev/null; echo "== server log"; cat "$RUNNER_TEMP/server.log"' EXIT
  for _ in $(seq 60); do
    curl -fsS "http://127.0.0.1:$port/healthz" > /dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "http://127.0.0.1:$port/healthz" > /dev/null
  TEST_BASE_URL="http://127.0.0.1:$port" npm run test:browser -- --grep-invert "$grep"
}

run_code() {
  part fmt cargo fmt --check
  part clippy cargo clippy --locked --all-targets --target-dir target/clippy -- -D warnings
  part generated bash .github/ci/generated.sh
  part ci-scripts ci_scripts
  part npm npm_install
  part build cargo build --locked --bin ip-info
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
# table to the job summary, and fails when any named part failed.
collect() {
  local name rc result seconds failed=0 span
  wait
  echo "| Part | Result | Seconds |" >> "$GITHUB_STEP_SUMMARY"
  echo "|---|---|---|" >> "$GITHUB_STEP_SUMMARY"
  for name in "$@"; do
    rc=
    [ -f "$EV/$name.rc" ] && rc=$(< "$EV/$name.rc")
    [ -n "$rc" ] || rc=missing
    seconds=
    if [ -f "$EV/$name.time" ]; then
      read -r -a span < "$EV/$name.time"
      seconds=$((span[1] - span[0]))
    fi
    case "$rc" in
      0) result=passed ;;
      missing) result="failed: no result (crashed or killed)" ;;
      *) result="failed: exit $rc" ;;
    esac
    echo "| $name | $result | $seconds |" >> "$GITHUB_STEP_SUMMARY"
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
  if [ "$code" = true ]; then
    run_code
    collect fmt clippy generated ci-scripts npm build rust-tests browser
  else
    run_docs
    collect generated ci-scripts
  fi
}

[ -n "${PARTS_LIB:-}" ] || main
