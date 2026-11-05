"""Bounded RSS/Atom ingestion; collection never calls a paid model."""

import ipaddress
import socket
import urllib.request
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import trafilatura

import db
from radar_core.config import CONFIG


def canonical_url(url):
    p = urlsplit(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("недопустимая ссылка")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")
    ]
    return urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            p.path or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def public_url(url):
    p = urlsplit(canonical_url(url))
    addresses = socket.getaddrinfo(
        p.hostname,
        p.port or (443 if p.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError("закрытый сетевой адрес")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    public_url(url)
    req = urllib.request.Request(
        url, headers={"User-Agent": "FintechChangeRadar/2.0 (+RSS research)"}
    )
    with urllib.request.build_opener(SafeRedirect).open(req, timeout=25) as r:
        data = r.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError("ответ превышает 4 МБ")
        return data


def plain(text):
    from html.parser import HTMLParser

    class Cleaner(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.hidden += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.hidden = max(0, self.hidden - 1)

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    parser = Cleaner()
    parser.feed(text or "")
    return " ".join(" ".join(parser.parts).split())


def entries(data):
    feed = feedparser.parse(data)
    if not feed.entries and feed.get("bozo"):
        raise ValueError("не удалось прочитать RSS/Atom")
    for e in feed.entries[: CONFIG["max_feed_items"]]:
        try:
            url = canonical_url(e.get("link", ""))
        except ValueError:
            continue
        date = dict(e).get("published_parsed") or dict(e).get("updated_parsed")
        moment = datetime(*date[:6], tzinfo=UTC) if date else None
        yield dict(
            url=url,
            title=plain(e.get("title", "")),
            text=plain(e.get("summary", ""))[: CONFIG["max_article_chars"]],
            published_at=moment,
        )


def article(url, fallback):
    try:
        text = trafilatura.extract(fetch(url), include_comments=False, include_tables=True)
        if text and len(text) > 300:
            mode = (
                "полный текст"
                if len(text) <= CONFIG["max_article_chars"]
                else f"Текст статьи: первые {CONFIG['max_article_chars']} символов"
            )
            return text[: CONFIG["max_article_chars"]], mode
    except Exception:
        pass
    return fallback, "описание; полный текст недоступен"


def collectable(published_at, now):
    """Keep all dated items available in the feed; reject only far-future dates."""
    return not published_at or published_at <= now + timedelta(hours=6)


def collect(conn, historical=False):
    if not conn.execute("SELECT pg_try_advisory_lock(4210)").fetchone()[0]:
        return 0
    run_id = db.start_run(conn, "collector")
    total = 0
    errors = []
    now = datetime.now(UTC)
    try:
        historical = (
            historical
            or not conn.execute(
                "SELECT 1 FROM radar_meta WHERE key='collection_initialized'"
            ).fetchone()
        )
        for sid, name, url in conn.execute(
            "SELECT id,name,url FROM sources WHERE active ORDER BY id"
        ).fetchall():
            try:
                items = list(entries(fetch(url)))
                dates = [x["published_at"] for x in items if x["published_at"]]
                conn.execute(
                    "INSERT INTO radar_source_checks(source_id,run_id,ok,items,oldest,newest,note) VALUES (%s,%s,true,%s,%s,%s,%s)",
                    (
                        sid,
                        run_id,
                        len(items),
                        min(dates) if dates else None,
                        max(dates) if dates else None,
                        "Архив ограничен доступной лентой",
                    ),
                )
                for x in items:
                    date = x["published_at"]
                    if not collectable(date, now):
                        continue
                    backfill = historical or not date or date < now - timedelta(hours=24)
                    row = conn.execute(
                        """INSERT INTO materials(source_id,run_id,url,title,text,published_at,radar_version,historical)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(url) DO NOTHING RETURNING id""",
                        (
                            sid,
                            run_id,
                            x["url"],
                            x["title"],
                            x["text"],
                            date,
                            CONFIG["rules_version"],
                            backfill,
                        ),
                    ).fetchone()
                    total += bool(row)
            except Exception as exc:
                errors.append(name)
                conn.execute(
                    "INSERT INTO radar_source_checks(source_id,run_id,ok,note) VALUES (%s,%s,false,%s)",
                    (sid, run_id, str(exc)[:300]),
                )
        db.finish_run(
            conn,
            "collector",
            run_id,
            total,
            "Новых: " + str(total) + ". Недоступны: " + (", ".join(errors) or "нет"),
        )
        conn.execute(
            "INSERT INTO radar_meta VALUES ('collection_initialized',now()::text) ON CONFLICT DO NOTHING"
        )
        return total
    except Exception as exc:
        db.fail_run(conn, "collector", run_id, exc)
        raise
    finally:
        conn.execute("SELECT pg_advisory_unlock(4210)")
