"""Run all published daily-batch workflows (WF14-18) via API."""

from __future__ import annotations

import sys
import time

import requests

BASE = "http://127.0.0.1:8888/api/v1"
WORKFLOW_IDS = [14, 15, 16, 17, 18]
POLL_INTERVAL = 2.0
POLL_TIMEOUT = 900.0


def _wait_run(headers: dict, run_id: int) -> tuple[str, float]:
    started = time.perf_counter()
    while True:
        resp = requests.get(f"{BASE}/workflows/runs/{run_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        status = resp.json().get("status", "unknown")
        if status not in {"pending", "running"}:
            return status, time.perf_counter() - started
        if time.perf_counter() - started > POLL_TIMEOUT:
            return "timeout", time.perf_counter() - started
        time.sleep(POLL_INTERVAL)


def main() -> int:
    login = requests.post(
        f"{BASE}/auth/login",
        json={"username": "admin", "password": "admin123456"},
        timeout=30,
    )
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    results: list[tuple[int, str, int | None, str]] = []
    for wf_id in WORKFLOW_IDS:
        print(f"Running workflow {wf_id} (daily, async)...", flush=True)
        started = time.perf_counter()
        resp = requests.post(
            f"{BASE}/workflows/{wf_id}/run",
            params={"batch_mode": "daily"},
            headers=headers,
            timeout=60,
        )
        if resp.status_code != 200:
            results.append((wf_id, "HTTP_ERROR", None, f"{resp.status_code} {resp.text[:200]}"))
            print(f"  FAIL HTTP {resp.status_code}: {resp.text[:200]}")
            continue
        body = resp.json()
        run_id = body.get("run_id")
        queued = body.get("status", "unknown")
        if queued == "pending" and run_id is not None:
            status, elapsed = _wait_run(headers, int(run_id))
        else:
            status = queued
            elapsed = time.perf_counter() - started
        msg = body.get("message", "")
        results.append((wf_id, status, run_id, msg))
        print(f"  {status} run_id={run_id} ({elapsed:.1f}s) {msg}")

    print("\n=== Summary ===")
    ok = all(s == "success" for _, s, _, _ in results)
    for wf_id, status, run_id, msg in results:
        print(f"WF{wf_id}: {status} (run #{run_id})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
