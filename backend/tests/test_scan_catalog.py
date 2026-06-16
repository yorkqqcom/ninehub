"""Tests for TIA scan local catalog merge."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.catalog.scan_catalog import local_api_names
from app.models.base import Base
from app.models.tia_override import TiaOverride


def test_local_api_names_only_overrides() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    assert local_api_names(session) == set()

    session.add(
        TiaOverride(
            api_name="balancesheet",
            data_type="tia_balancesheet",
            label="Balancesheet",
            min_points=600,
        )
    )
    session.commit()
    names = local_api_names(session)
    assert names == {"balancesheet"}
    session.close()
