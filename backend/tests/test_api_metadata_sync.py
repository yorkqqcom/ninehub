"""Tests for ApiMetadataSyncService (wctapi patch sidebar/page cache)."""

import httpx
import json
import pytest
import respx

from app.services.tia.scan.api_metadata_sync_service import ApiMetadataSyncService

HSGT_MD = """
## 沪深股通十大成交股
----
接口：hsgt_top10
描述：获取沪股通、深股通每日前十大成交
积分：需2000积分才可以多次调取

**输入参数**
名称 | 类型 | 必选 | 描述
---- | ----- | ---- | ----
trade_date | str | N | 交易日期

**输出参数**
名称 | 类型 | 描述
--- | ---- | ----
trade_date | str | 交易日期 |
ts_code | str | 股票代码 |
"""


@respx.mock
def test_metadata_sync_patches_sidebar_api(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tia.scan import api_spec_store
    from app.services.tia.doc_pages_sync_service import DocPagesSyncService

    specs_file = tmp_path / "specs.json"
    sidebar_file = tmp_path / "sidebar.json"
    cache_file = tmp_path / "pages.json"

    sidebar_file.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "doc_id": 48,
                        "api": "fina_indicator",
                        "label": "财务指标",
                        "category": "股票数据",
                        "resolved": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_spec_store, "_SPECS_CACHE_PATH", specs_file)
    monkeypatch.setattr(
        "app.services.tia.scan.api_metadata_sync_service.SIDEBAR_PATH",
        sidebar_file,
    )
    monkeypatch.setattr(
        "app.services.tia.doc_pages_sync_service.CACHE_PATH",
        cache_file,
    )

    respx.get("https://tushare.pro/wctapi/documents/48.md").mock(
        return_value=httpx.Response(200, text=HSGT_MD)
    )

    svc = ApiMetadataSyncService()
    result = svc.run([48], validate_sdk=False, sleep_seconds=0, rebuild_registry=False, regenerate_default_proposals=False)

    assert result["spec_sync"]["synced_count"] == 1
    sidebar = json.loads(sidebar_file.read_text(encoding="utf-8"))
    entry = sidebar["entries"][0]
    assert entry["api"] == "hsgt_top10"
    assert result["sidebar"]["api_fixed"] == 1

    pages = DocPagesSyncService().load_cache_pages()
    assert pages["48"]["api"] == "hsgt_top10"
