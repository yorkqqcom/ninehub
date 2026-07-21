"""Pytest configuration with in-memory SQLite."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_async_session
from app.core.deps import get_current_user
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.base import Base
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.browser import BrowserWatchlist, BrowserTemplate, BrowserQueryAudit  # noqa: F401
from app.models.user import User
from app.models.workflow import WorkflowEdge, WorkflowNode  # noqa: F401
from app.models.data_source import DataSource  # noqa: F401
from app.models.quality import QualityReport, QualityRule  # noqa: F401
from app.models.platform_setting import PlatformSetting  # noqa: F401
from app.models.tia_override import TiaOverride  # noqa: F401
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.sync_task import SyncTask  # noqa: F401


@pytest.fixture(autouse=True)
def catalog_test_entry():
    from catalog_test_support import register_test_catalog_entry, unregister_test_catalog_entry

    register_test_catalog_entry()
    yield
    unregister_test_catalog_entry()


@pytest.fixture(autouse=True)
def celery_use_delay(monkeypatch):
    """Tests mock .delay(); disable inline fallback so dispatch uses Celery."""
    monkeypatch.setenv("CELERY_INLINE_FALLBACK", "false")
    from app.core.config import get_settings
    from app.services.watch.watch_webhook_runtime import get_watch_webhook_runtime

    get_settings.cache_clear()
    get_watch_webhook_runtime().reset()
    yield
    get_settings.cache_clear()
    get_watch_webhook_runtime().reset()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        username="admin_test",
        hashed_password=get_password_hash("testpass123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def normal_user(db_session: AsyncSession) -> User:
    user = User(
        username="normal_test",
        hashed_password=get_password_hash("testpass123"),
        role="normal",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, admin_user: User) -> AsyncClient:
    async def override_session():
        yield db_session

    async def override_user():
        return admin_user

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token({"sub": admin_user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def normal_client(db_session: AsyncSession, normal_user: User) -> AsyncClient:
    async def override_session():
        yield db_session

    async def override_user():
        return normal_user

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def normal_headers(normal_user: User) -> dict[str, str]:
    token = create_access_token({"sub": normal_user.username})
    return {"Authorization": f"Bearer {token}"}
