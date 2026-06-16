"""Register a catalog entry for API/integration tests."""

from app.catalog.registry import CATALOG_REGISTRY, DataTypeEntry, register_catalog_entry
from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta

TEST_DATA_TYPE = "tia_income"
TEST_DATA_TYPE_LABEL = "利润表"


def register_test_catalog_entry() -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type=TEST_DATA_TYPE,
            domain="financial",
            label=TEST_DATA_TYPE_LABEL,
            table_name=None,
            is_activated=True,
            browse_enabled=False,
            min_points=120,
            columns=[
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="end_date", label="报告期", type="date"),
            ],
            filters=[
                CatalogFilterMeta(key="stock_code", label="股票代码", filter_type="stock_picker"),
            ],
        )
    )


def unregister_test_catalog_entry() -> None:
    CATALOG_REGISTRY.pop(TEST_DATA_TYPE, None)
