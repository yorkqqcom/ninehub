"""Batch retry L3 activation for all failed TIA proposals (wctapi doc fallback)."""
import os
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService

limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0

url = (
    os.environ.get("DATABASE_URL", "postgresql://ninehub:ninehub@127.0.0.1:5432/ninehub")
    .replace("+asyncpg", "")
)
engine = create_engine(url)
Session = sessionmaker(bind=engine)
session = Session()

rows = session.execute(
    text("select id, api_name from tia_proposals where status = 'failed' order by api_name")
).fetchall()
if limit:
    rows = rows[:limit]
print(f"Retrying {len(rows)} failed proposals...")

jobs_svc = PlatformJobService()
activation = TiaActivationService()
ok, fail = 0, 0
errors: list[tuple[str, str]] = []

for pid, api in rows:
    job = jobs_svc.create_sync(session, "tia_activate")
    job.result_json = {"proposal_id": pid, "reapply": True}
    session.commit()
    try:
        result = activation.execute_activation_sync(session, job.id)
        status = session.execute(
            text("select status from tia_proposals where id=:id"), {"id": pid}
        ).scalar()
        if status == "applied":
            ok += 1
            print(f"  OK  {api} -> {result.get('data_type')}")
        else:
            fail += 1
            errors.append((api, f"status={status}"))
            print(f"  ??  {api} status={status}")
    except Exception as exc:
        session.rollback()
        fail += 1
        msg = str(exc)[:300]
        errors.append((api, msg))
        print(f"  FAIL {api}: {msg}")

session.close()
print(f"\nDone: {ok} applied, {fail} failed")
if errors:
    print("Errors:")
    for api, msg in errors:
        print(f"  - {api}: {msg}")
    sys.exit(1 if fail else 0)
