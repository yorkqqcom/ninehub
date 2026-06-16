"""TIA quality rule auto-setup tests."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.quality import QualityRule
from app.services.tia.quality_setup_service import TiaQualitySetupService
from catalog_test_support import TEST_DATA_TYPE, register_test_catalog_entry


def test_setup_default_rules_uses_fields_config() -> None:
    register_test_catalog_entry()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    schema = {"unique_keys": ["stock_code", "end_date"]}
    created = TiaQualitySetupService().setup_default_rules(session, TEST_DATA_TYPE, schema)
    session.commit()
    assert created == 3
    rules = session.execute(
        select(QualityRule).where(QualityRule.target_data_type == TEST_DATA_TYPE)
    ).scalars().all()
    no_null_rules = [r for r in rules if r.rule_type == "no_nulls"]
    assert len(no_null_rules) == 2
    field_sets = {tuple(r.config_json["fields"]) for r in no_null_rules}
    assert field_sets == {("stock_code",), ("end_date",)}
    session.close()
