"""TIA scan credentials resolution tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.data_source import DataSource
from app.services.tia.credentials import resolve_tushare_scan_credentials


def test_credentials_skip_source_without_token() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add(
        DataSource(
            name="empty-token",
            provider="tushare",
            status="active",
            config={"account_points": 5000},
        )
    )
    session.add(
        DataSource(
            name="with-token",
            provider="tushare",
            status="active",
            config={"token": "abc123", "account_points": 2000},
        )
    )
    session.commit()

    creds = resolve_tushare_scan_credentials(session)
    assert creds["source_name"] == "with-token"
    assert creds["token"] == "abc123"
    assert creds["account_points"] == 2000
    assert creds["max_calls_per_minute"] == 200
    session.close()
