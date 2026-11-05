"""The required check `gate`: waits for this run's other jobs and passes only when they passed.

It starts with them instead of after them (no `needs`), so it adds no runner boot to the run, and
its check exists from the run's start: a run in progress reads as pending, never as a pass. It learns
each job's outcome from this run's jobs endpoint. `changes` and `artifacts` must succeed; `rust` must
succeed, or be skipped for a docs-only pull request as .github/ci/changes.sh classifies it (CODE).
A missing, failed, cancelled or wrongly skipped job fails the gate, and so does a job still
unfinished at the deadline.
"""

import json
import os
import sys
import time
import urllib.request

REQUIRED = ("changes", "artifacts", "rust")
POLL_SECONDS = 15
DEADLINE_SECONDS = 45 * 60
# How long a failed job of an earlier attempt may stand before the gate takes it as final: a re-run
# of failed jobs creates their new attempt shortly after the gate's, and a re-run of the gate alone
# never creates one.
STALE_SECONDS = 3 * 60


def jobs() -> list:
    url = "%s/repos/%s/actions/runs/%s/jobs?filter=all&per_page=100" % (
        os.environ["GITHUB_API_URL"], os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    listed = payload.get("jobs") or []
    if payload.get("total_count", 0) > len(listed):
        raise RuntimeError("the jobs listing is longer than one page")
    return listed


def newest(listed: list) -> dict:
    """Each required job's newest attempt (filter=all lists every attempt's)."""
    found = {}
    for job in listed:
        name = job.get("name")
        key = (job.get("run_attempt") or 0, job.get("id") or 0)
        if name in REQUIRED and (name not in found or key > found[name][0]):
            found[name] = (key, job)
    return {name: job for name, (_, job) in found.items()}


def settled(found: dict, attempt: int, waited: float) -> bool:
    for name in REQUIRED:
        job = found.get(name)
        if job is None or job.get("status") != "completed":
            return False
        old = (job.get("run_attempt") or 0) < attempt
        if old and job.get("conclusion") != "success" and waited < STALE_SECONDS:
            return False
    return True


def verdict(found: dict, code: str) -> list:
    errors = []
    for name in REQUIRED:
        job = found.get(name)
        state = "missing" if job is None else (job.get("conclusion") or job.get("status"))
        if state == "success":
            continue
        if name == "rust" and state == "skipped" and code == "false":
            print("rust skipped: docs-only change")
            continue
        errors.append("%s job %s" % (name, state))
    return errors


def main() -> int:
    code = os.environ["CODE"]
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    print("code=%s attempt=%d" % (code, attempt))
    start = time.monotonic()
    found = {}
    while True:
        waited = time.monotonic() - start
        try:
            found = newest(jobs())
        except Exception as error:  # a failed read is retried until the deadline, never a pass
            print("jobs read failed: %s" % error)
            found = {}
        else:
            if settled(found, attempt, waited):
                break
        if waited > DEADLINE_SECONDS:
            print("::error::deadline: the run's jobs did not finish")
            break
        time.sleep(POLL_SECONDS)
    for name in REQUIRED:
        job = found.get(name) or {}
        print("%s: attempt %s, %s %s" % (name, job.get("run_attempt"), job.get("status"),
                                         job.get("conclusion")))
    errors = verdict(found, code)
    for error in errors:
        print("::error::" + error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
