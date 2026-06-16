"""One-off: move closing-data cron from 16:00/20:00 to 18:00."""
from sqlalchemy import create_engine, text

url = "postgresql://ninehub:ninehub@127.0.0.1:5432/ninehub"
engine = create_engine(url)
with engine.begin() as conn:
    r1 = conn.execute(
        text("UPDATE workflows SET schedule_cron = '0 18 * * 1-5' WHERE schedule_cron = '0 16 * * 1-5'")
    )
    r2 = conn.execute(
        text(
            "UPDATE workflows SET schedule_cron = '0 18 * * 5' "
            "WHERE schedule_cron IN ('0 16 * * 5', '0 20 * * 5')"
        )
    )
    r3 = conn.execute(
        text("UPDATE sync_tasks SET schedule_cron = '0 18 * * 1-5' WHERE schedule_cron = '0 16 * * 1-5'")
    )
    r4 = conn.execute(
        text("UPDATE sync_tasks SET schedule_cron = '0 18 * * 5' WHERE schedule_cron = '0 20 * * 5'")
    )
    print(f"workflows weekday: {r1.rowcount}, workflows friday: {r2.rowcount}")
    print(f"sync_tasks weekday: {r3.rowcount}, sync_tasks friday: {r4.rowcount}")
