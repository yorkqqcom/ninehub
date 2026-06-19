"""Indicator registry label resolution."""

from app.catalog.registry import DataTypeEntry, register_catalog_entry
from app.schemas.catalog import CatalogColumnMeta
from app.services.query.indicator_registry import (
    IndicatorRegistry,
    _resolve_column_label,
)


def test_resolve_column_label_from_tushare_doc() -> None:
    entry = DataTypeEntry(
        data_type="tushare_daily",
        domain="market",
        label="日线行情",
        is_activated=True,
        columns=[CatalogColumnMeta(key="close", label="close", type="number")],
    )
    label = _resolve_column_label(entry, "close", yaml_label=None, catalog_label="close")
    assert label == "收盘价"


def test_yaml_override_beats_doc_label() -> None:
    entry = DataTypeEntry(
        data_type="tushare_daily",
        domain="market",
        label="日线行情",
        is_activated=True,
        columns=[CatalogColumnMeta(key="close", label="close", type="number")],
    )
    label = _resolve_column_label(entry, "close", yaml_label="Wind收盘价", catalog_label="close")
    assert label == "Wind收盘价"


def test_list_indicators_uses_chinese_labels() -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_daily",
            domain="market",
            label="日线行情",
            table_name="tushare_daily",
            is_activated=True,
            columns=[
                CatalogColumnMeta(key="close", label="close", type="number"),
                CatalogColumnMeta(key="vol", label="vol", type="number"),
            ],
        )
    )
    refs = IndicatorRegistry().list_indicators()
    close = next(r for r in refs if r.id == "tushare_daily.close")
    vol = next(r for r in refs if r.id == "tushare_daily.vol")
    assert close.label == "收盘价"
    assert vol.label == "成交量"


def test_search_indicators_pinyin() -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type="tushare_daily",
            domain="market",
            label="日线行情",
            table_name="tushare_daily",
            is_activated=True,
            columns=[
                CatalogColumnMeta(key="close", label="close", type="number"),
            ],
        )
    )
    results = IndicatorRegistry().search_indicators(q="spj")
    assert any(r.id == "tushare_daily.close" for r in results)
