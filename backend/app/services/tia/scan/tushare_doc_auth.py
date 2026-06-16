"""Playwright login / storage-state for Tushare document/2 SPA pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import get_settings

_LOGIN_URL = "https://tushare.pro/login"
_DEFAULT_STORAGE = Path(__file__).resolve().parents[4] / "data" / "tushare_doc_storage.json"


def resolve_storage_path() -> Path:
    settings = get_settings()
    if settings.tushare_doc_storage_path:
        return Path(settings.tushare_doc_storage_path)
    return _DEFAULT_STORAGE


def storage_state_exists() -> bool:
    path = resolve_storage_path()
    return path.is_file() and path.stat().st_size > 0


class TushareDocAuthSession:
    """Reusable authenticated Playwright browser context for doc page fetch."""

    def __init__(
        self,
        *,
        storage_path: Path | None = None,
        headless: bool = True,
        login_if_needed: bool = True,
    ) -> None:
        self._storage_path = storage_path or resolve_storage_path()
        self._headless = headless
        self._login_if_needed = login_if_needed
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def __enter__(self) -> TushareDocAuthSession:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        ctx_opts: dict[str, Any] = {}
        if self._storage_path.is_file():
            ctx_opts["storage_state"] = str(self._storage_path)
        self._context = self._browser.new_context(**ctx_opts)
        if self._login_if_needed and not self._is_authenticated():
            if not self._try_login():
                raise RuntimeError(
                    "Tushare 文档页未登录：请在 TIA「文档站登录」配置账号，"
                    "或设置 TUSHARE_DOC_USERNAME/PASSWORD，"
                    f"或提供 storage 文件 {self._storage_path}"
                )
            self._save_storage()
        return self

    def __exit__(self, *args: object) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    @property
    def context(self) -> Any:
        if self._context is None:
            raise RuntimeError("TushareDocAuthSession not started")
        return self._context

    def _is_authenticated(self) -> bool:
        page = self._context.new_page()
        try:
            page.goto(
                "https://tushare.pro/document/2?doc_id=26",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(600)
            text = page.inner_text("body")
            return "接口" in text and len(text) > 200
        except Exception:
            return False
        finally:
            page.close()

    def _try_login(self) -> bool:
        from app.services.tia.tushare_doc_credential_service import resolve_doc_credentials

        username, password = resolve_doc_credentials()
        if not username or not password:
            return False
        page = self._context.new_page()
        try:
            page.goto(_LOGIN_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(500)
            for selector in (
                'input[name="username"]',
                'input[name="phone"]',
                'input[placeholder*="手机"]',
                'input[type="text"]',
            ):
                if page.locator(selector).count():
                    page.locator(selector).first.fill(username)
                    break
            page.locator('input[type="password"]').first.fill(password)
            for selector in ('button[type="submit"]', "button.login-btn", "text=登录"):
                if page.locator(selector).count():
                    page.locator(selector).first.click()
                    break
            page.wait_for_timeout(2000)
            return self._is_authenticated()
        except Exception:
            return False
        finally:
            page.close()

    def _save_storage(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self._storage_path))

    def fetch_page_html(self, doc_id: int, *, timeout_ms: int = 30000) -> str:
        page = self._context.new_page()
        try:
            url = f"https://tushare.pro/document/2?doc_id={doc_id}"
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(800)
            return page.content()
        finally:
            page.close()
