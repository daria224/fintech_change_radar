"""Read-only source and extraction probe. No model calls, database, or Telegram."""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar_core.analysis import MODEL, candidate, prices
from radar_core.collect import article, entries, fetch
from radar_core.config import CONFIG


def main():
    if "--probe" in sys.argv:
        for url in [
            "https://habr.com/ru/rss/hubs/finance/all/?limit=100",
            "https://habr.com/ru/rss/hubs/finance/articles/?limit=100",
            "https://habr.com/ru/rss/hubs/fintech/articles/?limit=100",
        ]:
            try:
                print(url, len(list(entries(fetch(url)))), flush=True)
            except Exception as exc:
                print(url, str(exc), flush=True)
        from radar_core.analysis import request_json

        m = next(x for x in request_json("/models")["data"] if x["id"] == MODEL)
        print(json.dumps(m["pricing"]))
        return
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sources": [],
        "model": MODEL,
    }
    for source in CONFIG["sources"]:
        row = dict(source)
        try:
            items = list(entries(fetch(source["url"])))
            dates = [x["published_at"].isoformat() for x in items if x["published_at"]]
            row.update(
                ok=True,
                items=len(items),
                oldest=min(dates) if dates else None,
                newest=max(dates) if dates else None,
            )
            promising = next((x for x in items if candidate(x["title"], x["text"])), None)
            row["sample"] = [
                dict(
                    x,
                    text=x["text"][:350],
                    published_at=str(x["published_at"]),
                    prefilter=candidate(x["title"], x["text"]),
                )
                for x in items[:2]
            ]
            if promising:
                text, mode = article(promising["url"], promising["text"])
                row["extraction"] = {
                    "url": promising["url"],
                    "mode": mode,
                    "chars": len(text),
                    "preview": text[:350],
                }
        except Exception as exc:
            row.update(ok=False, error=str(exc)[:250])
        report["sources"].append(row)
        print(source["name"], row["ok"], row.get("items"), flush=True)
    try:
        report["price_per_token"] = list(map(str, prices()))
    except Exception as exc:
        report["price_error"] = str(exc)
    target = Path(__file__).resolve().parents[1] / "reports/live_sources.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(target))


if __name__ == "__main__":
    main()
