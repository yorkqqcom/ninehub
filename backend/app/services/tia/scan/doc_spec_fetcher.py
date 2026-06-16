"""Fetch Tushare wctapi markdown for document/2 interface pages."""

from __future__ import annotations

import httpx

from app.services.tia.scan.doc_spec_parser import build_wctapi_md_url, parse_wctapi_markdown, ApiDocSpec

_DEFAULT_HEADERS = {
    "User-Agent": "NineHub-TIA/1.0 (+https://github.com/ninehub)",
    "Accept": "text/markdown,text/plain,*/*",
}


def fetch_doc_spec(doc_id: int, *, timeout: float = 20.0) -> dict:
    """Fetch and parse wctapi markdown for one doc_id."""
    url = build_wctapi_md_url(doc_id)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers=_DEFAULT_HEADERS)
    except httpx.HTTPError as exc:
        return {
            "doc_id": doc_id,
            "error": str(exc),
            "fetched_url": url,
            "fetcher": "wctapi_md",
        }

    if response.status_code != 200:
        return {
            "doc_id": doc_id,
            "error": f"HTTP {response.status_code}",
            "fetched_url": url,
            "fetcher": "wctapi_md",
            "http_status": response.status_code,
        }

    text = response.text
    spec = parse_wctapi_markdown(doc_id, text)
    if spec is None:
        return {
            "doc_id": doc_id,
            "error": "failed to parse api name or params",
            "fetched_url": url,
            "fetcher": "wctapi_md",
            "raw_md_preview": text[:500],
        }

    out = spec.to_dict()
    out["fetcher"] = "wctapi_md"
    out["http_status"] = response.status_code
    out["raw_md_length"] = len(text)
    return out


def fetch_doc_spec_model(doc_id: int, *, timeout: float = 20.0) -> ApiDocSpec | None:
    from app.services.tia.scan.probe_spec_from_doc import api_doc_spec_from_cache_row

    row = fetch_doc_spec(doc_id, timeout=timeout)
    if row.get("error") or not row.get("api"):
        return None
    return api_doc_spec_from_cache_row(row)
