"""CatalogQueryService null count tests."""

from sqlalchemy import Column, MetaData, String, Table, insert, create_engine
from sqlalchemy.orm import sessionmaker

from app.catalog.registry import CATALOG_REGISTRY, DataTypeEntry, register_catalog_entry
from app.schemas.catalog import CatalogColumnMeta
from app.services.catalog_query import CatalogQueryService

TABLE_DATA_TYPE = "tia_income_fact"


def _register_fact_catalog() -> None:
    register_catalog_entry(
        DataTypeEntry(
            data_type=TABLE_DATA_TYPE,
            domain="financial",
            label="利润表",
            table_name="income_fact",
            is_activated=True,
            browse_enabled=False,
            min_points=120,
            columns=[
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="end_date", label="报告期", type="date"),
            ],
            filters=[],
        )
    )


def test_count_nulls_sync_aggregates_all_rows() -> None:
    _register_fact_catalog()
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "income_fact",
        metadata,
        Column("stock_code", String),
        Column("end_date", String),
    )
    metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.execute(
        insert(metadata.tables["income_fact"]),
        [
            {"stock_code": "000001.SZ", "end_date": "20231231"},
            {"stock_code": "000002.SZ", "end_date": None},
            {"stock_code": None, "end_date": "20231231"},
        ],
    )
    session.commit()

    service = CatalogQueryService()
    counts = service.count_nulls_sync(session, TABLE_DATA_TYPE, ["stock_code", "end_date"])
    assert counts == {"stock_code": 1, "end_date": 1}

    scoped = service.count_nulls_sync(
        session,
        TABLE_DATA_TYPE,
        ["end_date"],
        filters={"stock_code": "000002.SZ"},
    )
    assert scoped == {"end_date": 1}
    session.close()
    CATALOG_REGISTRY.pop(TABLE_DATA_TYPE, None)
