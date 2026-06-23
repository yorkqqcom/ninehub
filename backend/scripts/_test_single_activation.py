"""One-off: retry L3 activation for one failed proposal (no token / wctapi fallback)."""
import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import sync_engine
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService

api_name = sys.argv[1] if len(sys.argv) > 1 else "bse_mapping"

session = Session(sync_engine)

row = session.execute(
    text(
        "select id, api_name from tia_proposals "
        "where api_name = :api and status = 'failed' limit 1"
    ),
    {"api": api_name},
).first()
if not row:
    row = session.execute(
        text(
            "select id, api_name from tia_proposals "
            "where status = 'failed' order by api_name limit 1"
        )
    ).first()
if not row:
    print("No failed proposals")
    sys.exit(1)

pid, api = row
print(f"Testing activation for {api} id={pid}")

jobs = PlatformJobService()
job = jobs.create_sync(session, "tia_activate")
job.result_json = {"proposal_id": pid, "reapply": True}
session.commit()

svc = TiaActivationService()
try:
    result = svc.execute_activation_sync(session, job.id)
    print("SUCCESS data_type=", result.get("data_type"))
    for step, meta in (result.get("steps") or {}).items():
        st = meta.get("status") if isinstance(meta, dict) else meta
        err = meta.get("error") if isinstance(meta, dict) else None
        line = f"  {step}: {st}"
        if err:
            line += f" err={str(err)[:300]}"
        print(line)
    p = session.execute(
        text("select status, reason from tia_proposals where id=:id"), {"id": pid}
    ).first()
    print("proposal status:", p)
except Exception as exc:
    session.rollback()
    print("FAILED:", type(exc).__name__, str(exc)[:800])
    sys.exit(2)
finally:
    session.close()
