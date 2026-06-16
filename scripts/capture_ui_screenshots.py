"""Capture NineHub UI screenshots after login; waits for API + loading indicators."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PIC_DIR = ROOT / "pic"
BASE_URL = "http://localhost:5173"
API_BASE = "http://localhost:5173"
USERNAME = "admin"
PASSWORD = "admin123456"
VIEWPORT = {"width": 1440, "height": 900}

LOADING_TEXTS = ("加载中…", "加载表清单…", "登录中…", "加载详情失败")


def wait_loading_gone(page: Page, timeout_ms: int = 20_000) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        visible = False
        for text in LOADING_TEXTS:
            loc = page.get_by_text(text, exact=False)
            if loc.count() and loc.first.is_visible():
                visible = True
                break
        if not visible:
            return
        page.wait_for_timeout(200)
    for text in LOADING_TEXTS:
        loc = page.get_by_text(text, exact=False)
        if loc.count():
            loc.first.wait_for(state="hidden", timeout=5_000)


def wait_get_apis(page: Page, patterns: list[str], timeout_ms: int = 45_000) -> None:
    if not patterns:
        return
    needed = set(patterns)
    seen: set[str] = set()

    def on_response(response) -> None:
        if response.request.method != "GET" or response.status != 200:
            return
        url = response.url
        for pattern in needed - seen:
            if pattern in url:
                seen.add(pattern)

    page.on("response", on_response)
    try:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if seen >= needed:
                return
            page.wait_for_timeout(150)
        missing = needed - seen
        if missing:
            print(f"  warn: timeout waiting APIs {missing}", file=sys.stderr)
    finally:
        page.remove_listener("response", on_response)


def goto_ready(page: Page, path: str, api_patterns: list[str]) -> None:
    needed = set(api_patterns)
    seen: set[str] = set()

    def on_response(response) -> None:
        if response.request.method != "GET" or response.status != 200:
            return
        url = response.url
        for pattern in needed - seen:
            if pattern in url:
                seen.add(pattern)

    page.on("response", on_response)
    try:
        page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + 45
        while time.time() < deadline and (not needed or seen < needed):
            page.wait_for_timeout(150)
        if needed - seen:
            print(f"  warn: missing APIs {needed - seen}", file=sys.stderr)
        page.wait_for_load_state("networkidle", timeout=30_000)
        wait_loading_gone(page)
        page.wait_for_timeout(600)
    finally:
        page.remove_listener("response", on_response)


def login(page: Page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.locator('input[type="url"]').fill(API_BASE)
    page.locator('input[autocomplete="username"]').fill(USERNAME)
    page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
    with page.expect_response(
        lambda r: "/api/v1/auth/login" in r.url and r.status == 200, timeout=30_000
    ):
        with page.expect_response(
            lambda r: "/api/v1/auth/me" in r.url and r.status == 200, timeout=30_000
        ):
            page.get_by_role("button", name="登录").click()
    page.locator(".app-shell").wait_for(state="visible", timeout=30_000)
    wait_get_apis(page, ["/api/v1/catalog/data-types", "/api/v1/workflows"])
    page.wait_for_load_state("networkidle")
    wait_loading_gone(page)
    page.wait_for_timeout(800)


def shot(page: Page, name: str) -> Path:
    out = PIC_DIR / f"{name}.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"  saved {out.relative_to(ROOT)}")
    return out


def maybe_enhance_tasks(page: Page) -> None:
    row = page.locator(".data-table tbody tr").first
    if not row.count():
        return
    needed = {"/runs"}
    seen: set[str] = set()

    def on_response(response) -> None:
        if response.request.method != "GET" or response.status != 200:
            return
        if "/runs" in response.url:
            seen.add("/runs")

    page.on("response", on_response)
    try:
        row.click()
        deadline = time.time() + 15
        while time.time() < deadline and seen < needed:
            page.wait_for_timeout(150)
        page.wait_for_load_state("networkidle")
        wait_loading_gone(page)
        page.wait_for_timeout(500)
    finally:
        page.remove_listener("response", on_response)


def maybe_enhance_workflows(page: Page) -> None:
    page.locator(".vue-flow").wait_for(state="visible", timeout=20_000)


def has_browse_types(page: Page) -> bool:
    import json
    import urllib.request

    req = urllib.request.Request(f"{BASE_URL}/api/v1/catalog/data-types")
    token = page.evaluate("() => localStorage.getItem('ninehub.token')")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return any(item.get("browse_enabled") for item in data.get("items", []))


def main() -> None:
    PIC_DIR.mkdir(parents=True, exist_ok=True)
    pages: list[tuple[str, str, list[str], str | None]] = [
        ("dashboard", "/", ["/api/v1/catalog/data-types", "/api/v1/workflows"], None),
        ("tasks", "/tasks", ["/api/v1/tasks"], "tasks"),
        (
            "workflows",
            "/workflows",
            ["/api/v1/workflows", "/graph"],
            "workflows",
        ),
        ("sources", "/sources", ["/api/v1/sources"], None),
        ("tia-proposals", "/tia", ["/api/v1/tia/proposals"], None),
        (
            "tia-standards",
            "/tia?tab=standards",
            ["/api/v1/catalog/data-standards"],
            None,
        ),
        (
            "tia-coverage",
            "/tia?tab=coverage",
            ["/api/v1/catalog/coverage"],
            None,
        ),
        (
            "quality",
            "/quality",
            ["/api/v1/quality/rules", "/api/v1/catalog/data-types"],
            None,
        ),
        (
            "settings",
            "/settings",
            ["/api/v1/platform/settings", "/api/v1/auth/users"],
            None,
        ),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)

        print("login …")
        login(page)
        shot(page, "login-authenticated-dashboard")

        browse_ok = has_browse_types(page)
        if browse_ok:
            pages.append(
                (
                    "browse",
                    "/browse",
                    ["/api/v1/catalog/data-types", "/api/v1/catalog/data/"],
                    "browse",
                )
            )
        else:
            print("  skip browse (no L3 browse_enabled types)")

        for name, path, apis, enhance in pages:
            print(f"capture {name} …")
            goto_ready(page, path, apis)
            if enhance == "tasks":
                maybe_enhance_tasks(page)
            elif enhance == "workflows":
                maybe_enhance_workflows(page)
            elif enhance == "browse":
                wait_get_apis(page, ["/api/v1/catalog/data/"])
                wait_loading_gone(page)
                page.wait_for_timeout(500)
            shot(page, name)

        browser.close()

    print(f"\nDone — {len(list(PIC_DIR.glob('*.png')))} files in pic/")


if __name__ == "__main__":
    main()
