"""Fetch Tushare document/2 interface pages and extract api + access min_points."""

from __future__ import annotations

import re
import time
from html import unescape
from typing import Callable

import httpx

from app.services.tia.scan.min_points_extractor import extract_access_min_points
from app.services.tia.scan.tushare_doc_registry import (
    build_doc_page_url,
    parse_api_name_from_doc_text,
)

_DOC_URL = "https://tushare.pro/document/2"
_DEFAULT_HEADERS = {
    "User-Agent": "NineHub-TIA/1.0 (+https://github.com/ninehub)",
    "Accept": "text/html,application/xhtml+xml",
}


def html_to_plain_text(html: str) -> str:
    """Strip tags/scripts; keep text for regex parsers."""
    if not html:
        return ""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def doc_page_url(doc_id: int) -> str:
    url = build_doc_page_url(doc_id)
    if url is None:
        raise ValueError(f"invalid doc_id: {doc_id}")
    return url


def parse_doc_page_content(raw_text: str) -> dict:
    """Return {api, min_points} parsed from interface page plain text."""
    api = parse_api_name_from_doc_text(raw_text)
    min_points = extract_access_min_points(raw_text)
    out: dict = {"raw_text": raw_text}
    if api:
        out["api"] = api
    if min_points is not None:
        out["min_points"] = min_points
    return out


def _is_spa_shell(text: str) -> bool:
    if len(text) > 800:
        return False
    lowered = text.lower()
    return "javascript enabled" in lowered or 'id="app"' in lowered


def entry_from_html(doc_id: int, html: str, *, fetcher: str) -> dict:
    """Build cache entry from rendered HTML."""
    url = doc_page_url(doc_id)
    raw_text = html_to_plain_text(html)
    if _is_spa_shell(raw_text):
        return {
            "error": "SPA shell only (page did not render)",
            "fetched_url": url,
            "fetcher": fetcher,
        }
    parsed = parse_doc_page_content(raw_text)
    parsed["fetched_url"] = url
    parsed["fetcher"] = fetcher
    parsed["min_points_source"] = "doc_page_live"
    return parsed


def fetch_doc_page_playwright(doc_id: int, *, timeout_ms: int = 30000) -> dict:
    """Headless browser fetch for Vue SPA doc pages (no login)."""
    from app.services.tia.scan.tushare_doc_auth import TushareDocAuthSession

    with TushareDocAuthSession(login_if_needed=False) as auth:
        html = auth.fetch_page_html(doc_id, timeout_ms=timeout_ms)
    return entry_from_html(doc_id, html, fetcher="playwright")


def fetch_doc_page_authenticated(
    doc_id: int,
    auth_session,
    *,
    timeout_ms: int = 30000,
) -> dict:
    """Fetch one doc page using an open TushareDocAuthSession."""
    html = auth_session.fetch_page_html(doc_id, timeout_ms=timeout_ms)
    return entry_from_html(doc_id, html, fetcher="playwright_auth")


def fetch_doc_page(
    doc_id: int,
    *,
    client: httpx.Client | None = None,
    sleep_seconds: float = 0.0,
    use_playwright: bool = True,
    auth_session=None,
) -> dict:
    """Fetch one doc page and return cache entry fields."""
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    if auth_session is not None:
        return fetch_doc_page_authenticated(doc_id, auth_session)

    url = doc_page_url(doc_id)
    owns_client = client is None
    http = client or httpx.Client(timeout=30.0, headers=_DEFAULT_HEADERS, follow_redirects=True)
    try:
        response = http.get(url)
        response.raise_for_status()
        raw_text = html_to_plain_text(response.text)
        if _is_spa_shell(raw_text) and use_playwright:
            try:
                return fetch_doc_page_playwright(doc_id)
            except ImportError:
                return {
                    "error": "SPA page requires playwright (pip install playwright && playwright install chromium)",
                    "fetched_url": url,
                    "http_status": response.status_code,
                }
            except Exception as exc:
                return {
                    "error": f"playwright fetch failed: {exc}",
                    "fetched_url": url,
                    "http_status": response.status_code,
                }
        if _is_spa_shell(raw_text):
            return {
                "error": "SPA shell only (install playwright for headless fetch)",
                "fetched_url": url,
                "http_status": response.status_code,
            }
        parsed = parse_doc_page_content(raw_text)
        parsed["fetched_url"] = url
        parsed["http_status"] = response.status_code
        parsed["fetcher"] = "httpx"
        parsed["min_points_source"] = "doc_page_live"
        return parsed
    except httpx.HTTPError as exc:
        return {"error": str(exc), "fetched_url": url}
    finally:
        if owns_client:
            http.close()


def fetch_doc_pages(
    doc_ids: list[int],
    *,
    sleep_seconds: float = 0.35,
    on_progress: Callable[[int, int, int], None] | None = None,
    use_playwright: bool = True,
    login_if_needed: bool = True,
) -> dict[str, dict]:
    """Fetch multiple doc pages; returns {doc_id_str: entry}."""
    pages: dict[str, dict] = {}
    total = len(doc_ids)

    if use_playwright:
        try:
            from app.services.tia.scan.tushare_doc_auth import TushareDocAuthSession

            with TushareDocAuthSession(login_if_needed=login_if_needed) as auth:
                for idx, doc_id in enumerate(doc_ids, start=1):
                    if on_progress:
                        on_progress(doc_id, idx, total)
                    if idx > 1 and sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                    pages[str(doc_id)] = fetch_doc_page(
                        doc_id,
                        auth_session=auth,
                        use_playwright=True,
                    )
            return pages
        except ImportError:
            pass
        except RuntimeError:
            raise

    with httpx.Client(timeout=30.0, headers=_DEFAULT_HEADERS, follow_redirects=True) as client:
        for idx, doc_id in enumerate(doc_ids, start=1):
            if on_progress:
                on_progress(doc_id, idx, total)
            pages[str(doc_id)] = fetch_doc_page(
                doc_id,
                client=client,
                sleep_seconds=sleep_seconds if idx > 1 else 0.0,
                use_playwright=False,
            )
    return pages
