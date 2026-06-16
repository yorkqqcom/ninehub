"""Catalog registry tests."""

from app.catalog.registry import get_data_type_entry, list_domains, list_data_types
from catalog_test_support import TEST_DATA_TYPE, TEST_DATA_TYPE_LABEL


def test_list_domains_has_seven_domains() -> None:
    domains = list_domains()
    assert len(domains) == 7


def test_test_catalog_entry_registered() -> None:
    entry = get_data_type_entry(TEST_DATA_TYPE)
    assert entry is not None
    assert entry.label == TEST_DATA_TYPE_LABEL
    assert len(entry.columns) >= 2


def test_unknown_data_type() -> None:
    assert get_data_type_entry("unknown_type") is None


def test_list_data_types_by_domain() -> None:
    financial = list_data_types(domain="financial")
    assert all(e.domain == "financial" for e in financial)
    assert any(e.data_type == TEST_DATA_TYPE for e in financial)
