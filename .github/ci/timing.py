#!/usr/bin/env python3
"""Timing report and slow-test guard of the `tier1` job (README.md, Development).

Reads the parts' NAME.time files (.github/ci/parts.sh), nextest's JUnit file
and Playwright's JSON report. Appends a Markdown report to
$GITHUB_STEP_SUMMARY, prints it, and exits 1 when:
  - on a pull request, a test not marked slow took over 60 s;
  - on any run, a test took 90 s or more;
  - on any run, the parts step took over 240 s;
  - a report it needs is missing or unreadable.
A Rust test is marked slow when SLOW_RUST_FILTER (.github/ci/pins.env)
matches its name, a Playwright test when it carries SLOW_BROWSER_TAG.

Run: python3 .github/ci/timing.py --event EVENT --code true|false --parts DIR
       --start DIR/parts.start --junit FILE --playwright FILE
Tested by tests/ci/test_timing.py.
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PINS = Path(__file__).with_name("pins.env")
PR_LIMIT = 60  # seconds, tests not marked slow on pull requests
TEST_LIMIT = 90  # seconds, any test on any run
PARTS_TARGET = 90
PARTS_LIMIT = 240
SLOWEST = 10


class ReportError(Exception):
    """A report file is missing or cannot be read."""


def read_pins(path=PINS):
    pins = {}
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            pins[key.strip()] = value.strip().strip("'\"")
    return pins


def read_parts(folder):
    """[(name, start, end)] from the NAME.time files, by start."""
    parts = []
    for path in sorted(Path(folder).glob("*.time")):
        start, end = (int(word) for word in path.read_text().split())
        parts.append((path.stem, start, end))
    return sorted(parts, key=lambda part: part[1])


def load(path, what, parse):
    try:
        return parse(Path(path))
    except FileNotFoundError:
        raise ReportError(f"no {what} at {path}") from None
    except (OSError, ValueError, ET.ParseError) as error:
        raise ReportError(f"cannot read the {what} at {path}: {error}") from None


def rust_tests(path, slow_filter):
    """[(kind, name, seconds, slow)] from nextest's JUnit file."""
    what = "Rust test report (nextest JUnit, from the rust-tests part)"
    root = load(path, what, lambda p: ET.parse(p).getroot())
    return [("rust", f"{case.get('classname', '')} {case.get('name', '')}".strip(),
             float(case.get("time") or 0), bool(re.search(slow_filter, case.get("name", ""))))
            for case in root.iter("testcase")]


def browser_tests(path, slow_tag):
    """[(kind, name, seconds, slow)] from Playwright's JSON report."""
    what = "browser test report (Playwright JSON, from the browser part)"
    report = load(path, what, lambda p: json.loads(p.read_text()))
    tests = []

    def walk(suite, titles):
        titles = titles + [suite["title"]] if suite.get("title") else titles
        for spec in suite.get("specs", []):
            # The JSON reporter writes tags without their "@".
            slow = slow_tag.lstrip("@") in (tag.lstrip("@") for tag in spec.get("tags", []))
            for test in spec.get("tests", []):
                ms = max((result.get("duration", 0) for result in test.get("results", [])), default=0)
                name = " › ".join(titles + [spec["title"]])
                tests.append(("browser", name, ms / 1000, slow))
        for child in suite.get("suites", []):
            walk(child, titles)

    for suite in report.get("suites", []):
        walk(suite, [])
    return tests


def broken_rules(event, tests, parts_seconds):
    errors = []
    for kind, name, seconds, slow in tests:
        if seconds >= TEST_LIMIT:
            errors.append(f"{name} took {seconds:.1f} s; every test must take under {TEST_LIMIT} s. "
                          "Make it faster or split it.")
        elif event == "pull_request" and not slow and seconds > PR_LIMIT:
            mark = ("rename the Rust test so it starts with `slow_`" if kind == "rust"
                    else "tag the Playwright test `@slow`")
            errors.append(f"{name} took {seconds:.1f} s, over {PR_LIMIT} s on a pull request. "
                          f"Mark it slow ({mark}): pull requests then skip it.")
    if parts_seconds > PARTS_LIMIT:
        errors.append(f"the parts step took {parts_seconds} s, over the {PARTS_LIMIT} s limit.")
    return errors


def render(parts, parts_seconds, tests, errors):
    lines = ["### Timing", "", "| Part | Starts at (s) | Ends at (s) | Seconds |", "|---|---|---|---|"]
    first = min((start for _, start, _ in parts), default=0)
    lines += [f"| {name} | {start - first} | {end - first} | {end - start} |" for name, start, end in parts]
    state = "over" if parts_seconds > PARTS_TARGET else "within"
    lines += ["", f"Parts step: {parts_seconds} s, {state} the {PARTS_TARGET} s target "
              f"(fails over {PARTS_LIMIT} s).", "", f"{SLOWEST} slowest tests:", "",
              "| Test | Kind | Seconds | Marked slow |", "|---|---|---|---|"]
    slowest = sorted(tests, key=lambda test: -test[2])[:SLOWEST]
    # A "|" in a test title would end its cell.
    lines += ["| {} | {} | {:.1f} | {} |".format(name.replace("|", "\\|"), kind, seconds, "yes" if slow else "no")
              for kind, name, seconds, slow in slowest]
    lines += ["", *(f"- **Failed:** {error}" for error in errors)]
    return "\n".join(lines) + "\n"


def read_tests(args):
    """(tests, errors): each report read on its own, so one missing still shows the other."""
    pins, tests, errors = read_pins(), [], []
    for part, read, path, pin in (("rust-tests", rust_tests, args.junit, "SLOW_RUST_FILTER"),
                                  ("browser", browser_tests, args.playwright, "SLOW_BROWSER_TAG")):
        try:
            tests += read(path, pins[pin])
        except ReportError as error:
            rc = Path(args.parts, f"{part}.rc")
            passed = rc.is_file() and rc.read_text().strip() == "0"
            errors.append(f"{error}" if passed else f"{error}: the {part} part did not pass, see its log")
    return tests, errors


def report(args, now):
    if args.code != "true":
        return "### Timing\n\ndocs-only: no tests ran\n", []
    try:
        start = int(load(args.start, "parts step start", lambda p: p.read_text()).strip())
        parts = read_parts(args.parts)
    except (ReportError, ValueError) as error:
        message = f"timing report not made: {error}"
        return f"### Timing\n\n- **Failed:** {message}\n", [message]
    parts_seconds = int(now) - start
    tests, errors = read_tests(args)
    errors += broken_rules(args.event, tests, parts_seconds)
    return render(parts, parts_seconds, tests, errors), errors


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--event", "--code", "--parts", "--start", "--junit", "--playwright"):
        parser.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    text, errors = report(args, time.time() if now is None else now)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as out:
            out.write(text)
    print(text)
    for error in errors:
        print(f"::error::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
