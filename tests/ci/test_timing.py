"""Tests .github/ci/timing.py with small JUnit and Playwright JSON reports.

Run: python3 -m unittest discover -s tests/ci -p 'test_*.py'
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("timing", ROOT / ".github/ci/timing.py")
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)

NOW = 1_800_000_000


def junit(*cases):
    """A nextest JUnit report with (name, seconds) test cases."""
    rows = "".join(f'<testcase name="{name}" classname="ip-info::api" time="{seconds}"/>'
                   for name, seconds in cases)
    return f'<?xml version="1.0"?><testsuites><testsuite name="ip-info::api">{rows}</testsuite></testsuites>'


def playwright(*specs):
    """A Playwright JSON report with (title, seconds, tags) specs."""
    return json.dumps({"suites": [{"title": "pages.spec.js", "specs": [
        {"title": title, "tags": tags, "tests": [{"results": [{"duration": seconds * 1000}]}]}
        for title, seconds, tags in specs]}]})


class TimingTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.parts = self.dir / "parts"
        self.parts.mkdir()
        (self.parts / "fmt.time").write_text(f"{NOW - 80} {NOW - 70}\n")
        (self.parts / "build.time").write_text(f"{NOW - 80} {NOW - 30}\n")
        self.summary = self.dir / "summary.md"
        self.write(start=NOW - 80, junit=junit(("lookup", 1)), playwright=playwright(("home", 1, [])))

    def write(self, start=None, junit=None, playwright=None):
        for name, text in (("parts/parts.start", start), ("junit.xml", junit), ("results.json", playwright)):
            if text is not None:
                (self.dir / name).write_text(f"{text}\n")

    def run_timing(self, event="pull_request", code="true", parts_seconds=None):
        if parts_seconds is not None:
            self.write(start=NOW - parts_seconds)
        argv = ["--event", event, "--code", code, "--parts", str(self.parts),
                "--start", str(self.parts / "parts.start"), "--junit", str(self.dir / "junit.xml"),
                "--playwright", str(self.dir / "results.json")]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                unittest.mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(self.summary)}):
            status = timing.main(argv, now=NOW)
        return status, out.getvalue(), self.summary.read_text()

    def test_report_from_real_shaped_files(self):
        self.write(junit=(FIXTURES / "junit.xml").read_text(),
                   playwright=(FIXTURES / "playwright.json").read_text())
        status, out, summary = self.run_timing()
        self.assertEqual(status, 0, out)
        self.assertIn("| fmt | 0 | 10 | 10 |", summary)
        self.assertIn("| build | 0 | 50 | 50 |", summary)
        self.assertIn("Parts step: 80 s, within the 90 s target", summary)
        rows = [line for line in summary.splitlines() if line.startswith("| ip-info") or "›" in line]
        self.assertEqual(rows, [
            "| ip-info::api cache::slow_refresh_cycle | rust | 12.4 | yes |",
            "| pages.spec.js › lookup › full table renders | browser | 4.2 | yes |",
            "| pages.spec.js › home page loads | browser | 1.5 | no |",
            "| ip-info::api lookup_returns_json | rust | 0.0 | no |",
            "| ip-info::api rejects_bad_ip | rust | 0.0 | no |",
        ])
        self.assertEqual(summary.strip(), out.strip())

    def test_ten_slowest_only(self):
        self.write(junit=junit(*((f"t{i}", i) for i in range(12))))
        _, _, summary = self.run_timing()
        self.assertIn("| ip-info::api t11 | rust | 11.0 |", summary)
        self.assertIn("| ip-info::api t2 | rust |", summary)
        self.assertNotIn("| ip-info::api t1 | rust |", summary)

    def test_pull_request_rust_test_over_60_s_fails(self):
        self.write(junit=junit(("api::lookup", 60)))
        self.assertEqual(self.run_timing()[0], 0)
        self.write(junit=junit(("api::lookup", 60.5)))
        status, out, summary = self.run_timing()
        self.assertEqual(status, 1)
        self.assertIn("::error::ip-info::api api::lookup took 60.5 s, over 60 s on a pull request", out)
        self.assertIn("starts with `slow_`", summary)

    def test_pull_request_browser_test_over_60_s_fails(self):
        self.write(playwright=playwright(("home", 61, ["db"])))
        status, out, _ = self.run_timing()
        self.assertEqual(status, 1)
        self.assertIn("::error::pages.spec.js › home took 61.0 s", out)
        self.assertIn("tag the Playwright test `@slow`", out)

    def test_pull_request_slow_marked_over_60_s_passes(self):
        self.write(junit=junit(("slow_full_scan", 75), ("api::slow_reload", 75)),
                   playwright=playwright(("home", 75, ["slow"]), ("about", 75, ["@slow"])))
        status, out, _ = self.run_timing()
        self.assertEqual(status, 0, out)

    def test_not_slow_when_slow_is_inside_the_name(self):
        self.write(junit=junit(("not_slow_scan", 61)))
        self.assertEqual(self.run_timing()[0], 1)

    def test_other_events_allow_over_60_s(self):
        self.write(junit=junit(("lookup", 89.9)), playwright=playwright(("home", 89.9, [])))
        for event in ("merge_group", "schedule", "workflow_dispatch"):
            self.assertEqual(self.run_timing(event)[0], 0, event)

    def test_any_test_at_90_s_fails(self):
        for event in ("pull_request", "schedule"):
            self.write(junit=junit(("slow_scan", 90)), playwright=playwright(("home", 1, [])))
            status, out, _ = self.run_timing(event)
            self.assertEqual(status, 1, event)
            self.assertIn("slow_scan took 90.0 s; every test must take under 90 s", out)
            self.write(junit=junit(("lookup", 1)), playwright=playwright(("home", 90, ["slow"])))
            self.assertEqual(self.run_timing(event)[0], 1, event)

    def test_parts_step_over_240_s_fails(self):
        status, out, summary = self.run_timing("schedule", parts_seconds=240)
        self.assertEqual(status, 0, out)
        self.assertIn("Parts step: 240 s, over the 90 s target", summary)
        status, out, _ = self.run_timing("schedule", parts_seconds=241)
        self.assertEqual(status, 1)
        self.assertIn("::error::the parts step took 241 s, over the 240 s limit.", out)

    def test_missing_reports_fail(self):
        for name, what in (("junit.xml", "Rust test report"), ("results.json", "browser test report"),
                           ("parts/parts.start", "parts step start")):
            with self.subTest(name):
                self.setUp()
                (self.dir / name).unlink()
                status, out, summary = self.run_timing("schedule")
                self.assertEqual(status, 1)
                self.assertIn(f"::error::timing report not made: no {what}", out)
                self.assertIn(str(self.dir / name), summary)

    def test_unreadable_reports_fail(self):
        for files in ({"junit": "<testsuites>"}, {"playwright": "{"}, {"start": "soon"}):
            with self.subTest(files):
                self.setUp()
                self.write(**files)
                status, out, _ = self.run_timing()
                self.assertEqual(status, 1)
                self.assertIn("::error::timing report not made:", out)

    def test_docs_only_passes_without_reports(self):
        for name in ("junit.xml", "results.json", "parts/parts.start"):
            (self.dir / name).unlink()
        status, _, summary = self.run_timing(code="false")
        self.assertEqual(status, 0)
        self.assertIn("docs-only: no tests ran", summary)

    def test_pins_hold_the_slow_rule(self):
        pins = timing.read_pins()
        self.assertEqual(pins["SLOW_BROWSER_TAG"], "@slow")
        tests = timing.rust_tests(FIXTURES / "junit.xml", pins["SLOW_RUST_FILTER"])
        self.assertEqual([test[1] for test in tests if test[3]], ["ip-info::api cache::slow_refresh_cycle"])


if __name__ == "__main__":
    unittest.main()
