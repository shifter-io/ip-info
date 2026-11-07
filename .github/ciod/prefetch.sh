#!/usr/bin/env bash
# Installs the tools CI would otherwise download on every run under
# $CI_CACHE_DIR/ip-info/tools, and prints for each whether it was already
# there (prefetched) or installed now.
#
# The nightly CI image build runs it with no argument from a fresh clone of
# main after `npm ci --ignore-scripts`, as a user that may write only
# $CI_CACHE_DIR/ip-info, with HOME=$CI_CACHE_DIR/ip-info. ci.yml runs it
# with one tool's name as the fallback for images built without it.
#   prefetch.sh [playwright] [markdown]
set -euo pipefail
: "${CI_CACHE_DIR:?is not set}"
# shellcheck source-path=SCRIPTDIR source=../ci/pins.env
. "$(dirname "$0")/../ci/pins.env"
tools="$CI_CACHE_DIR/ip-info/tools"
export npm_config_update_notifier=false

# package-lock.json pins Playwright and so the browser build. Headless runs
# need only the headless shell; no --with-deps (no sudo on the CI servers).
playwright() {
  export PLAYWRIGHT_BROWSERS_PATH="$tools/ms-playwright"
  local dir state="installed now"
  dir=$(npx playwright install --dry-run --only-shell chromium | sed -n 's/^ *Install location: *//p' | head -n 1)
  [ -n "$dir" ] && [ -f "$dir/INSTALLATION_COMPLETE" ] && state=prefetched
  # Install anyway: it downloads nothing when every part is complete.
  npx playwright install --only-shell chromium
  echo "playwright: $state ${dir:-under $PLAYWRIGHT_BROWSERS_PATH}"
}

# A virtual environment cannot move, so it is built in place and marked complete.
markdown() {
  local dir="$tools/markdown-$MARKDOWN_VERSION" req
  if [ -f "$dir/.complete" ]; then
    echo "markdown: prefetched $dir"
    return
  fi
  rm -rf "$dir"
  python3 -m venv "$dir"
  req=$(mktemp)
  echo "markdown==$MARKDOWN_VERSION --hash=sha256:$MARKDOWN_SHA256" > "$req"
  "$dir/bin/pip" install --quiet --no-cache-dir --disable-pip-version-check --require-hashes --only-binary :all: -r "$req"
  rm -f "$req"
  touch "$dir/.complete"
  echo "markdown: installed now $dir"
}

[ "$#" -gt 0 ] || set -- playwright markdown
for tool in "$@"; do
  case "$tool" in
    playwright | markdown) "$tool" ;;
    *) echo "prefetch.sh: unknown tool '$tool'" >&2; exit 2 ;;
  esac
done
