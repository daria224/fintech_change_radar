"""Shared helpers: connection to the database and run log."""

import os
import sys
from pathlib import Path

import psycopg

SCHEMA = Path(__file__).with_name("schema.sql")


def connect():
    if os.environ.get("RADAR_DB_HOST"):
        return psycopg.connect(
            host=os.environ["RADAR_DB_HOST"],
            port=int(os.environ.get("RADAR_DB_PORT", "5432")),
            dbname=os.environ["RADAR_DB_NAME"],
            user=os.environ["RADAR_DB_USER"],
            password=os.environ.get("RADAR_DB_PASSWORD", ""),
            autocommit=True,
        )
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


SCHEMA_LOCK = 4207  # any fixed number shared by all blocks


def init_schema(conn):
    # blocks start at the same time on a fresh database; the lock lets one create the tables
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK,))
    try:
        with conn.transaction():
            conn.execute(SCHEMA.read_text(encoding="utf-8"))
            conn.execute(SCHEMA.with_name("radar.sql").read_text(encoding="utf-8"))
            from radar_core.config import CONFIG

            if not conn.execute("SELECT 1 FROM radar_meta WHERE key='installed'").fetchone():
                conn.execute("UPDATE sources SET active=false")
                conn.execute("INSERT INTO radar_meta VALUES ('installed', now()::text)")
            for source in CONFIG["sources"]:
                conn.execute(
                    "INSERT INTO sources(name,kind,url,active) VALUES (%s,'rss',%s,true) ON CONFLICT(name) DO UPDATE SET url=excluded.url,active=true",
                    (source["name"], source["url"]),
                )
            conn.execute(
                "UPDATE sources SET active=false WHERE NOT(name=ANY(%s))",
                ([s["name"] for s in CONFIG["sources"]],),
            )
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK,))


def log(service, message):
    print(f"[{service}] {message}", file=sys.stdout, flush=True)


def start_run(conn, service):
    run_id = conn.execute(
        "INSERT INTO runs (service, status) VALUES (%s, 'started') RETURNING id",
        (service,),
    ).fetchone()[0]
    log(service, f"прогон {run_id} начат")
    return run_id


def progress_run(conn, service, run_id, items, note):
    conn.execute(
        "UPDATE runs SET status = 'running', items = %s, note = %s WHERE id = %s",
        (items, note, run_id),
    )
    log(service, f"прогон {run_id} идет: {note}")


def finish_run(conn, service, run_id, items, note):
    conn.execute(
        "UPDATE runs SET status = 'finished', items = %s, note = %s, finished_at = now() WHERE id = %s",
        (items, note, run_id),
    )
    log(service, f"прогон {run_id} завершен: {note}")


def fail_run(conn, service, run_id, error):
    conn.execute(
        "UPDATE runs SET status = 'failed', note = %s, finished_at = now() WHERE id = %s",
        (str(error)[:500], run_id),
    )
    log(service, f"прогон {run_id} упал: {error}")
