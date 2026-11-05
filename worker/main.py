import os
import sys
import time
from datetime import UTC, datetime

import db
from radar_core.analysis import process
from radar_core.collect import collect
from radar_core.config import CONFIG


def tick(conn):
    now = datetime.now(UTC)
    slot = now.strftime("%Y-%m-%d") + ":" + str(now.hour // CONFIG["collect_hours"])
    if not conn.execute("SELECT pg_try_advisory_lock(4213)").fetchone()[0]:
        return
    try:
        job = conn.execute(
            "SELECT state,updated_at<now()-interval '30 minutes' FROM radar_jobs WHERE job='collect' AND slot=%s",
            (slot,),
        ).fetchone()
        if not job or (job[0] != "done" and job[1]):
            conn.execute(
                "INSERT INTO radar_jobs(job,slot) VALUES ('collect',%s) ON CONFLICT(job,slot) DO UPDATE SET updated_at=now()",
                (slot,),
            )
            first = not conn.execute(
                "SELECT 1 FROM radar_meta WHERE key='backfill_done'"
            ).fetchone()
            collect(conn, historical=first)
            conn.execute(
                "INSERT INTO radar_meta VALUES ('backfill_done',now()::text) ON CONFLICT DO NOTHING"
            )
            conn.execute(
                "UPDATE radar_jobs SET state='done',updated_at=now() WHERE job='collect' AND slot=%s",
                (slot,),
            )
    finally:
        conn.execute("SELECT pg_advisory_unlock(4213)")
    # Enabling a model alone must never drain the historical queue. Bulk analysis
    # is a separate, explicit deployment setting; the manual pilot is ID-scoped.
    if os.environ.get("RADAR_AI_AUTO_PROCESS", "false").strip().casefold() == "true":
        process(conn, automatic=True)


def main():
    if "--once" in sys.argv:
        with db.connect() as conn:
            db.init_schema(conn)
            tick(conn)
        return
    while True:
        try:
            with db.connect() as conn:
                db.init_schema(conn)
                while True:
                    tick(conn)
                    time.sleep(30)
        except Exception as exc:
            db.log("worker", f"Ошибка: {type(exc).__name__}; повтор через 30 с")
            time.sleep(30)


if __name__ == "__main__":
    main()
