"""Capture Data Browser wizard screenshots (multi-step flow)."""

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

LOADING_TEXTS = ("加载中…", "加载元数据…", "查询中…", "登录中…")


def wait_loading_gone(page: Page, timeout_ms: int = 30_000) -> None:
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
    page.wait_for_load_state("networkidle")
    wait_loading_gone(page)
    page.wait_for_timeout(600)


def shot(page: Page, name: str) -> Path:
    out = PIC_DIR / f"{name}.png"
    page.screenshot(path=str(out), full_page=False)
    print(f"  saved {out.relative_to(ROOT)}")
    return out


def wait_browser_meta(page: Page) -> None:
    seen = False

    def on_response(response) -> None:
        nonlocal seen
        if (
            response.request.method == "GET"
            and response.status == 200
            and "/api/v1/query/browser/meta" in response.url
        ):
            seen = True

    page.on("response", on_response)
    try:
        page.goto(f"{BASE_URL}/data-browser", wait_until="domcontentloaded", timeout=60_000)
        deadline = time.time() + 45
        while time.time() < deadline and not seen:
            page.wait_for_timeout(150)
        page.wait_for_load_state("networkidle", timeout=30_000)
        wait_loading_gone(page)
        page.wait_for_timeout(800)
    finally:
        page.remove_listener("response", on_response)


def load_demo_template(page: Page) -> None:
    tpl_btn = page.get_by_role("button", name="OHLC 演示")
    if tpl_btn.count():
        tpl_btn.first.click()
        page.wait_for_timeout(400)
        return
    page.goto(
        f"{BASE_URL}/data-browser?tpl=wind_ohlc_demo",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    wait_loading_gone(page)
    page.wait_for_timeout(800)


def capture_browser_flow(page: Page) -> None:
    print("capture data browser …")

    # Step 1 — 选范围（预设证券池）
    wait_browser_meta(page)
    shot(page, "browser-step1-scope")

    # Step 2 — 选指标（系统模板 OHLC 演示）
    page.goto(f"{BASE_URL}/data-browser?tpl=wind_ohlc_demo", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    wait_loading_gone(page)
    page.get_by_role("button", name="下一步：选指标", exact=False).click()
    page.locator(".browser-triple-body").wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(600)
    shot(page, "browser-step2-indicators")

    # Step 3 — 选时间（小样本自定义代码，加快提取）
    page.locator("button.browser-wizard__step").nth(0).click()
    page.get_by_text("自定义代码", exact=False).click()
    page.locator(".browser-codes-input").fill("000001.SZ\n600900.SH\n000002.SZ")
    page.wait_for_timeout(800)
    page.locator("button.browser-wizard__step").nth(2).click()
    page.locator('input[type="date"]').first.fill("2024-11-18")
    page.wait_for_timeout(400)
    shot(page, "browser-step3-time")

    extract = page.get_by_role("button", name="提取数据", exact=False)
    extract.first.wait_for(state="visible", timeout=10_000)
    with page.expect_response(
        lambda r: "/api/v1/query/browser/execute" in r.url and r.status == 200,
        timeout=120_000,
    ):
        extract.first.click()
    wait_loading_gone(page)
    page.locator(".data-table tbody tr").first.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(800)
    shot(page, "browser-result-table")

    chart_btn = page.locator("button").filter(has_text="图")
    if chart_btn.count():
        chart_btn.last.click()
        page.wait_for_timeout(1500)
        shot(page, "browser-result-chart")


def main() -> None:
    PIC_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        print("login …")
        login(page)
        capture_browser_flow(page)
        browser.close()
    print(f"\nDone — browser screenshots in pic/")


if __name__ == "__main__":
    main()
