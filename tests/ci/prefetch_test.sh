#!/usr/bin/env bash
# Tests .github/ciod/prefetch.sh's cargo-llvm-cov and diff-cover in a scratch
# tree with its own pins.env, and fake curl and python3 first on PATH: curl
# copies $FAKE_ASSET to its -o path; python3 -m venv makes a pip that logs its
# arguments to $FAKE_LOG.
# Run: bash tests/ci/prefetch_test.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/bin" "$work/tree/.github/ci" "$work/tree/.github/ciod" "$work/asset"
cp "$root/.github/ciod/prefetch.sh" "$work/tree/.github/ciod/"
cp "$root/.github/ci/coverage-requirements.txt" "$work/tree/.github/ci/"
cat > "$work/bin/curl" <<'FAKE'
#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  [ "$1" = -o ] && exec cp "$FAKE_ASSET" "$2"
  shift
done
exit 1
FAKE
cat > "$work/bin/python3" <<'FAKE'
#!/usr/bin/env bash
[ "$1 $2" = "-m venv" ] || exit 1
mkdir -p "$3/bin"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "pip $*" >> "$FAKE_LOG"\n' > "$3/bin/pip"
chmod +x "$3/bin/pip"
FAKE
chmod +x "$work/bin/"*
echo fake > "$work/asset/cargo-llvm-cov"
tar -czf "$work/asset.tar.gz" -C "$work/asset" cargo-llvm-cov
real_sha=$(sha256sum "$work/asset.tar.gz" | cut -d' ' -f1)
diff_cover=$(sed -n 's/^diff-cover==\([^ ]*\) .*/\1/p' "$root/.github/ci/coverage-requirements.txt")

export PATH="$work/bin:$PATH" FAKE_LOG="$work/log" FAKE_ASSET="$work/asset.tar.gz"
failures=0
fail() {
  echo "FAIL: $1"
  failures=$((failures + 1))
}

# run SHA256 DIFF_COVER_VERSION TOOL...: runs prefetch.sh with these pins in a
# fresh cache; sets $status and $out.
run() {
  local sha=$1 version=$2
  shift 2
  printf 'MARKDOWN_VERSION=1\nMARKDOWN_SHA256=0\nCARGO_LLVM_COV_VERSION=9.9.9\nCARGO_LLVM_COV_SHA256=%s\nDIFF_COVER_VERSION=%s\n' \
    "$sha" "$version" > "$work/tree/.github/ci/pins.env"
  : > "$FAKE_LOG"
  status=0
  out=$(CI_CACHE_DIR="$work/cache" bash "$work/tree/.github/ciod/prefetch.sh" "$@" 2>&1) || status=$?
}
tools="$work/cache/ip-info/tools"

# The release asset with the pinned checksum: unpacked, then reused.
rm -rf "$work/cache"
run "$real_sha" "$diff_cover" cargo-llvm-cov
[ "$status" = 0 ] || fail "asset: exit $status ($out)"
[ "$(cat "$tools/cargo-llvm-cov-9.9.9/cargo-llvm-cov")" = fake ] || fail "asset: binary not unpacked: $out"
grep -q "^cargo-llvm-cov: installed now" <<< "$out" || fail "asset: state: $out"
run "$real_sha" "$diff_cover" cargo-llvm-cov
grep -q "^cargo-llvm-cov: prefetched" <<< "$out" || fail "asset again: state: $out"

# Another checksum: fails, and leaves nothing marked complete.
rm -rf "$work/cache"
run 0000 "$diff_cover" cargo-llvm-cov
[ "$status" != 0 ] || fail "bad checksum: exit 0 ($out)"
[ ! -e "$tools/cargo-llvm-cov-9.9.9/.complete" ] || fail "bad checksum: marked complete"

# diff-cover: installed only from the hash-pinned requirements.
rm -rf "$work/cache"
run "$real_sha" "$diff_cover" diff-cover
[ "$status" = 0 ] || fail "diff-cover: exit $status ($out)"
grep -q -- "--require-hashes --only-binary :all: -r .*/coverage-requirements.txt$" "$FAKE_LOG" ||
  fail "diff-cover: pip command: $(cat "$FAKE_LOG")"
[ -f "$tools/diff-cover-$diff_cover/.complete" ] || fail "diff-cover: not marked complete"

# pins.env names a version the requirements do not pin: fails before pip.
rm -rf "$work/cache"
run "$real_sha" 0.0.1 diff-cover
[ "$status" != 0 ] || fail "version mismatch: exit 0 ($out)"
grep -q "does not pin diff-cover 0.0.1" <<< "$out" || fail "version mismatch: message: $out"
[ ! -s "$FAKE_LOG" ] || fail "version mismatch: pip ran: $(cat "$FAKE_LOG")"

if [ "$failures" != 0 ]; then
  echo "$failures failure(s)"
  exit 1
fi
echo "prefetch_test: all passed"
