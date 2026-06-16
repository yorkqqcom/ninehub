"""One-off: dump failed proposal activation_steps."""
import json
import os
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL") or "postgresql://ninehub:ninehub@127.0.0.1:5432/ninehub"
e = create_engine(url.replace("+asyncpg", ""))
with e.connect() as c:
    rows = c.execute(
        text(
            "select id, api_name, status, reason, activation_steps "
            "from tia_proposals where status = 'failed' order by api_name"
        )
    ).fetchall()
    print("failed count:", len(rows))
    for pid, api, status, reason, steps in rows[:12]:
        steps = steps or {}
        print(f"\n=== {api} id={pid} reason={reason} ===")
        if isinstance(steps, dict):
            for k, v in steps.items():
                if isinstance(v, dict):
                    st = v.get("status")
                    err = v.get("error") or v.get("message")
                    if st == "failed" or err:
                        print(f"  {k}: status={st} err={str(err)[:300]}")
                else:
                    print(f"  {k}: {str(v)[:120]}")
