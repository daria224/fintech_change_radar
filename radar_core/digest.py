"""Immutable daily selection and per-recipient delivery state."""

import html
from collections import defaultdict
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from radar_core.config import CONFIG, MSK


def rank(card):
    return (
        card["applicability"] * 4 + card["novelty"] * 2 + card["evidence"] * 3 + card["urgency"] * 3
    )


def select_events(events, limit=5):
    remaining = sorted(events, key=lambda e: (-rank(e["card"]), e["id"]))
    result = []
    themes = set()
    while remaining and len(result) < limit:
        best = rank(remaining[0]["card"])
        ties = [e for e in remaining if rank(e["card"]) == best]
        chosen = next((e for e in ties if e["mechanism"] not in themes), ties[0])
        remaining.remove(chosen)
        result.append(chosen)
        themes.add(chosen["mechanism"])
    return result


def signal(events):
    groups = defaultdict(list)
    for e in events:
        pattern = " ".join(e["card"].get("pattern", "").casefold().split())
        if len(pattern) < 15 or pattern in CONFIG["mechanisms"]:
            continue
        groups[pattern].append(e)
    for pattern, items in sorted(groups.items(), key=lambda x: -len(x[1])):
        representatives = []
        seen_companies, seen_quotes = set(), set()
        for item in items:
            company = item["company"].casefold().strip()
            quote = " ".join(item.get("quote", "").casefold().split())
            if company not in seen_companies and quote and quote not in seen_quotes:
                representatives.append(item)
                seen_companies.add(company)
                seen_quotes.add(quote)
            if len(representatives) == 5:
                break
        companies = {x["company"].casefold() for x in items}
        # Reprints share an event id; identical quoted evidence cannot prove a second event.
        if (
            len(companies) >= 2
            and len({x["id"] for x in items}) >= 2
            and len({x.get("quote", "") for x in items}) >= 2
            and len(representatives) >= 2
        ):
            return {
                "text": f"Общий сигнал: «{pattern}» встречается у нескольких компаний. Это основание исследовать механику, но пока не вывод о массовом распространении или пользе для банка.",
                "event_ids": [x["id"] for x in representatives],
                "rules_version": CONFIG["rules_version"],
            }
    return None


def event_rows(conn, where="", params=()):
    rows = conn.execute(
        """SELECT e.id,e.company,e.event_date,e.mechanism,e.card,e.historical,e.created_at,
       (SELECT m.url FROM radar_evidence v JOIN materials m ON m.id=v.material_id WHERE v.event_id=e.id ORDER BY m.id LIMIT 1),
       (SELECT quote FROM radar_evidence v WHERE v.event_id=e.id ORDER BY material_id LIMIT 1)
       ,e.model,e.rules_version FROM radar_events e """
        + where,
        params,
    ).fetchall()
    keys = (
        "id",
        "company",
        "event_date",
        "mechanism",
        "card",
        "historical",
        "created_at",
        "url",
        "quote",
        "model",
        "rules_version",
    )
    return [dict(zip(keys, r)) for r in rows]


def coverage(conn):
    rows = conn.execute("""SELECT s.name,c.ok,c.checked_at FROM sources s LEFT JOIN LATERAL
       (SELECT ok,checked_at FROM radar_source_checks WHERE source_id=s.id ORDER BY id DESC LIMIT 1) c ON true
       WHERE s.active ORDER BY s.id""").fetchall()
    now = datetime.now(MSK)
    bad = [name for name, ok, when in rows if not ok or not when or now - when > timedelta(hours=8)]
    return "Проверка неполная: " + ", ".join(bad) + "." if bad else "Все стартовые ленты проверены."


def build(conn, now=None):
    now = now or datetime.now(MSK)
    now = now.astimezone(MSK)
    if now.hour < CONFIG["digest_hour_moscow"]:
        return None
    day = now.date()
    cutoff = now.replace(hour=CONFIG["digest_hour_moscow"], minute=0, second=0, microsecond=0)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(4214)")
        old = conn.execute("SELECT text FROM radar_digests WHERE day=%s", (day,)).fetchone()
        if old:
            return day, old[0]
        events = event_rows(
            conn,
            """WHERE NOT e.historical AND e.created_at<=%s AND EXISTS
          (SELECT 1 FROM radar_evidence v JOIN materials m ON m.id=v.material_id WHERE v.event_id=e.id
           AND NOT m.historical AND m.published_at>%s AND m.published_at<=%s)
          AND NOT EXISTS (SELECT 1 FROM radar_digests d WHERE e.id=ANY(d.event_ids))""",
            (cutoff, cutoff - timedelta(days=1), cutoff),
        )
        selected = select_events(events)
        recent = event_rows(
            conn,
            "WHERE e.event_date>=%s AND e.created_at<=%s ORDER BY e.id DESC LIMIT 500",
            (day - timedelta(days=CONFIG["history_days"]), cutoff),
        )
        common = signal(recent)
        # A daily general signal needs at least one newly selected event, not archive-only repetition.
        if common and not set(common["event_ids"]) & {e["id"] for e in selected}:
            common = None
        esc = html.escape
        text = f"<b>Радар изменений · {day:%d.%m.%Y}</b>\n"
        if not selected:
            text += "\nНовых подтверждённых событий для сводки пока нет.\n"
        for e in selected:
            c = e["card"]
            text += f"\n• <b>{esc(c['title'][:120])}</b> · {esc(e['company'][:60])}\n{esc(c['interpretation'][:180])}\n"
            text += f'<a href="{esc(e["url"], quote=True)}">Основание</a>\n'
        if common:
            by_id = {e["id"]: e for e in recent}
            text += (
                "\n"
                + esc(common["text"])
                + "\nОснования: "
                + ", ".join(
                    f'<a href="{esc(by_id[i]["url"], quote=True)}">Событие №{i}</a>'
                    for i in common["event_ids"]
                )
                + "\n"
            )
        text += "\n" + esc(coverage(conn))
        pending = conn.execute(
            "SELECT count(*) FROM materials WHERE radar_version IS NOT NULL AND status IN ('new','deferred','failed')"
        ).fetchone()[0]
        if pending:
            text += f"\nОжидают анализа: {pending}. Бюджет и ошибки могут задерживать выводы."
        text += "\nПолные карточки, ранние сигналы и ограничения — в ленте."
        conn.execute(
            "INSERT INTO radar_digests(day,text,event_ids,signal) VALUES (%s,%s,%s,%s)",
            (day, text, [e["id"] for e in selected], Jsonb(common) if common else None),
        )
        conn.execute(
            "INSERT INTO radar_deliveries(day,chat_id) SELECT %s,chat_id FROM subscribers WHERE active ON CONFLICT DO NOTHING",
            (day,),
        )
        return day, text


def deliver(conn, say, now=None):
    digest = build(conn, now)
    if digest is None:
        return
    day, text = digest
    for (chat_id,) in conn.execute(
        "SELECT chat_id FROM radar_deliveries WHERE day=%s AND state='pending' ORDER BY chat_id",
        (day,),
    ).fetchall():
        # Commit a claim before Telegram: ambiguous outcomes are not automatically retried.
        claim = conn.execute(
            "UPDATE radar_deliveries SET state='sending',updated_at=now() WHERE day=%s AND chat_id=%s AND state='pending' RETURNING chat_id",
            (day, chat_id),
        ).fetchone()
        if not claim:
            continue
        try:
            result = say(chat_id, text)
            conn.execute(
                "UPDATE radar_deliveries SET state='sent',message_id=%s,updated_at=now() WHERE day=%s AND chat_id=%s",
                ((result or {}).get("message_id"), day, chat_id),
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            state = "pending" if code == 429 else ("blocked" if code == 403 else "uncertain")
            conn.execute(
                "UPDATE radar_deliveries SET state=%s,note=%s,updated_at=now() WHERE day=%s AND chat_id=%s",
                (state, type(exc).__name__, day, chat_id),
            )
            if code == 403:
                conn.execute("UPDATE subscribers SET active=false WHERE chat_id=%s", (chat_id,))
            if code == 429:
                break
