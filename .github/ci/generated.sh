#!/usr/bin/env bash
# The `generated` part of .github/ci/parts.sh: the Docker build uses the
# pinned Rust release, the generated files are fresh, and the offline
# artifact checks pass.
#
# It works in its own copy of the tree ($RUNNER_TEMP/gen): generate_site.py
# rewrites src/response.rs, tests/*.json and web/ (which the binary embeds)
# while the build and clippy read them; build_test_mmdb.py rewrites
# tests/fixtures/*.mmdb. Needs MARKDOWN_PYTHON, a Python with
# Markdown for scripts/render_readme.py.
set -euo pipefail
: "${RUNNER_TEMP:?}" "${MARKDOWN_PYTHON:?is not set; the tools step sets it}"
copy="$RUNNER_TEMP/gen"
git worktree add --quiet --detach "$copy" HEAD
# An EXIT trap does not change the exit status.
trap 'git worktree remove --force "$copy"' EXIT
cd "$copy"

channel=$(sed -n 's/^channel = "\([0-9.]*\)"$/\1/p' rust-toolchain.toml)
minor=${channel%.*}
echo "rust-toolchain.toml: ${channel:-missing}; $(grep -m1 '^FROM rust:' Dockerfile)"
# The image may name the release (rust:1.94.1-...) or its line (rust:1.94-...).
if [ -z "$channel" ] || ! grep -qE "^FROM rust:(${channel//./\\.}|${minor//./\\.})-" Dockerfile; then
  echo "::error::the Dockerfile's Rust image must use rust-toolchain.toml's release"
  exit 1
fi

python3 --version
python3 scripts/generate_site.py
python3 scripts/build_test_mmdb.py
"$MARKDOWN_PYTHON" scripts/render_readme.py
git status --short
if [ -n "$(git status --porcelain)" ]; then
  echo "::error::regenerate with scripts/generate_site.py, scripts/build_test_mmdb.py and scripts/render_readme.py and commit the result"
  exit 1
fi
python3 scripts/validate_artifacts.py
