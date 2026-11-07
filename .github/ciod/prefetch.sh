#!/usr/bin/env bash
# Installs the tools CI would otherwise download on every run under
# $CI_CACHE_DIR/ip-info/tools, and prints for each whether it was already
# there (prefetched) or installed now.
#
# The nightly CI image build runs it with no argument from a fresh clone of
# main after `npm ci --ignore-scripts`, as a user that may write only
# $CI_CACHE_DIR/ip-info, with HOME=$CI_CACHE_DIR/ip-info. ci.yml runs it
# with the names of the tools it needs as the fallback for images built
# without them.
#   prefetch.sh [playwright] [markdown] [cargo-llvm-cov] [diff-cover]
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

# venv NAME DIR REQUIREMENTS: a virtual environment cannot move, so it is
# built in place from hash-pinned wheels and marked complete.
venv() {
  local name=$1 dir=$2 req=$3
  if [ -f "$dir/.complete" ]; then
    echo "$name: prefetched $dir"
    return
  fi
  rm -rf "$dir"
  python3 -m venv "$dir"
  "$dir/bin/pip" install --quiet --no-cache-dir --disable-pip-version-check --require-hashes --only-binary :all: -r "$req"
  touch "$dir/.complete"
  echo "$name: installed now $dir"
}

markdown() {
  local req
  req=$(mktemp)
  echo "markdown==$MARKDOWN_VERSION --hash=sha256:$MARKDOWN_SHA256" > "$req"
  venv markdown "$tools/markdown-$MARKDOWN_VERSION" "$req"
  rm -f "$req"
}

diff_cover() {
  local req
  req="$(dirname "$0")/../ci/coverage-requirements.txt"
  if ! grep -qx "diff-cover==$DIFF_COVER_VERSION \\\\" "$req"; then
    echo "prefetch.sh: $req does not pin diff-cover $DIFF_COVER_VERSION (pins.env)" >&2
    return 1
  fi
  venv diff-cover "$tools/diff-cover-$DIFF_COVER_VERSION" "$req"
}

# One binary from the release asset, checked against its pinned SHA-256.
cargo_llvm_cov() {
  local dir="$tools/cargo-llvm-cov-$CARGO_LLVM_COV_VERSION" asset
  if [ -f "$dir/.complete" ]; then
    echo "cargo-llvm-cov: prefetched $dir"
    return
  fi
  rm -rf "$dir"
  mkdir -p "$dir"
  asset="$dir/asset.tar.gz"
  curl -fsSL --retry 3 -o "$asset" \
    "https://github.com/taiki-e/cargo-llvm-cov/releases/download/v$CARGO_LLVM_COV_VERSION/cargo-llvm-cov-x86_64-unknown-linux-gnu.tar.gz"
  echo "$CARGO_LLVM_COV_SHA256  $asset" | sha256sum --check --quiet
  tar -xzf "$asset" -C "$dir" cargo-llvm-cov
  rm -f "$asset"
  touch "$dir/.complete"
  echo "cargo-llvm-cov: installed now $dir"
}

[ "$#" -gt 0 ] || set -- playwright markdown cargo-llvm-cov diff-cover
for tool in "$@"; do
  case "$tool" in
    playwright | markdown | cargo-llvm-cov | diff-cover) "${tool//-/_}" ;;
    *) echo "prefetch.sh: unknown tool '$tool'" >&2; exit 2 ;;
  esac
done
