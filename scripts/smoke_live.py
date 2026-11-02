"""Live collection into a disposable test DB; no paid calls or Telegram delivery."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(root))
os.environ["DATABASE_URL"] = (
    "postgresql://radar_test:radar_local_test_only@127.0.0.1:55432/radar_test"
)
import db
from bot.main import render_page, status_text
from radar_core.analysis import process
from radar_core.collect import collect


def main():
    with db.connect() as conn:
        assert conn.info.dbname == "radar_test"
        db.init_schema(conn)
        conn.execute(
            "TRUNCATE radar_deliveries,radar_digests,radar_evidence,radar_events,radar_spend,radar_source_checks,materials,findings,runs,subscribers,radar_jobs RESTART IDENTITY CASCADE"
        )
        conn.execute(
            "DELETE FROM radar_meta WHERE key IN ('collection_initialized','backfill_done','analysis_state')"
        )
        added = collect(conn, historical=True)
        repeat = collect(conn, historical=True)
        # Explicitly remove the key even if the parent environment supplies one.
        os.environ.pop("OPENROUTER_API_KEY", None)
        process(conn, limit=1)
        rows = conn.execute("""SELECT s.name,count(m.id),min(m.published_at),max(m.published_at)
            FROM sources s LEFT JOIN materials m ON m.source_id=s.id AND m.radar_version IS NOT NULL
            WHERE s.active GROUP BY s.id ORDER BY s.id""").fetchall()
        report = {
            "checked_at": datetime.now(UTC).isoformat(),
            "added": added,
            "repeat_added": repeat,
            "sources": [
                dict(source=r[0], materials=r[1], oldest=str(r[2]), newest=str(r[3])) for r in rows
            ],
            "spend_calls": conn.execute("SELECT count(*) FROM radar_spend").fetchone()[0],
            "status": status_text(conn),
            "model_check": "Не выполнен: ключ отсутствует. Платные вызовы и доставка отключены.",
        }
        (root / "reports/live_collection.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "reports/feed_preview.html").write_text(render_page(conn), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
