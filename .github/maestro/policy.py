#!/usr/bin/env python3
"""The `maestro-policy` CI check: PR size, privacy and AI attribution. Standard library and git only.

  maestro-policy --base <ref> --head <ref> [--pr-body-file FILE]

Size counts changed lines (added + deleted) of production files between the merge base and head. Files the
repo's .gitattributes marks `linguist-generated` (GitHub's own marker) are generated and don't count.
Warning above 400, failure above 800 unless the PR body has a `Size-exception:` line approved by the owner.
Privacy scans added lines for absolute home paths, private keys and tokens.
Attribution scans commit messages and the PR body. Exit 1 on any failure.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

WARN, HARD = 400, 800
NOT_PRODUCTION = ("*.md", "*.rst", "*.txt", "docs/*", "*/docs/*", "test/*", "tests/*", "*/test/*", "*/tests/*",
                  "test_*", "*/test_*", "*_test.*", "*.test.*", "*.spec.*", "testdata/*", "*/testdata/*",
                  "*/fixtures/*", "*/golden/*", "*/generated/*", "vendor/*", "*.snap", "*.lock", "go.sum",
                  "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "LICENSE*")
PRIVATE = (("an absolute home path", re.compile(r"/(Users|home)/(?!(runner|ubuntu|runneradmin)/)[A-Za-z][\w.-]*/")),
           ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
           ("a token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_.-]{20,}|github_[p]at_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}"
                                  r"|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}|dop_v[1]_[a-f0-9]{20,})")))
PLACEHOLDER = re.compile(r"FAKE|EXAMPLE", re.I)  # test fixtures and documentation keys
AI = r"(claude|anthropic|openai|chatgpt|copilot|cursor|gemini|codex)"
ATTRIBUTION = (re.compile(r"^[ \t]*co-authored-by:[^\n]*\b" + AI + r"\b", re.I | re.M),
               re.compile(r"noreply@anthropic\.com", re.I),
               re.compile("\U0001f916"),
               re.compile(r"generated (?:with|by)\s*\[?\s*(?:" + AI + r"|an? ai\b)", re.I))


def git(*args):
    return subprocess.run(["git"] + list(args), check=True, capture_output=True, text=True).stdout


def production(path):
    return not any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(os.path.basename(path), pat)
                   for pat in NOT_PRODUCTION)


def generated(paths):
    """The paths .gitattributes marks `linguist-generated` (set or true), read at the checked-out head."""
    if not paths:
        return set()
    out = subprocess.run(["git", "check-attr", "-z", "linguist-generated", "--"] + list(paths),
                         capture_output=True, text=True).stdout.split("\0")
    return {out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] in ("set", "true")}


def size(numstat, skip=frozenset()):
    """Changed production lines from `git diff --numstat` output; binary and `skip` files count 0."""
    total = 0
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        if production(path) and path not in skip and added != "-":
            total += int(added) + int(deleted)
    return total


def privacy(diff):
    """Problems in added lines of a unified diff, as 'file: what'."""
    found, current = [], "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            if not PLACEHOLDER.search(line):
                found += ["%s: %s" % (current, what) for what, rx in PRIVATE if rx.search(line)]
    return sorted(set(found))


def attribution(text):
    return any(rx.search(text) for rx in ATTRIBUTION)


def check(base, head, body):
    merge_base = git("merge-base", base, head).strip()
    errors, notes = [], []
    numstat = git("diff", "--numstat", "--no-renames", merge_base, head)
    lines = size(numstat, generated([ln.split("\t", 2)[2] for ln in numstat.splitlines()]))
    notes.append("size: %d changed production lines" % lines)
    if lines > HARD and not re.search(r"^Size-exception:\s*\S", body, re.M):
        errors.append("size: %d > %d; split the work or add an owner-approved `Size-exception:` line" % (lines, HARD))
    elif lines > WARN:
        notes.append("size: above %d, the PR body must say why the change belongs together" % WARN)
    errors += ["privacy: " + p for p in privacy(git("diff", "--no-renames", merge_base, head))]
    if attribution(git("log", "--format=%B", "%s..%s" % (merge_base, head))):
        errors.append("attribution: a commit message carries AI attribution")
    if attribution(body):
        errors.append("attribution: the PR body carries AI attribution")
    return errors, notes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--pr-body-file")
    a = ap.parse_args(argv)
    body = open(a.pr_body_file).read() if a.pr_body_file else ""
    errors, notes = check(a.base, a.head, body)
    report = "\n".join(notes + ["FAIL " + e for e in errors] + ["ok" if not errors else ""]).strip()
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("```\n%s\n```\n" % report)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
