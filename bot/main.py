"""Existing Telegram identity and subscribers; daily digest and card feed."""

import html
import json
import os
import threading
import time
import urllib.request
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
from radar_core.config import CONFIG, MSK
from radar_core.digest import coverage, deliver, event_rows, signal

SERVICE = "bot"
COMMANDS = [
    {"command": "start", "description": "подписаться на утреннюю сводку"},
    {"command": "status", "description": "проверить сбор и бюджет"},
]


def setting(name):
    return os.environ.get(name, "").strip()


def page_url():
    url = setting("MINI_APP_URL") or setting("RAILWAY_PUBLIC_DOMAIN") or setting("COOLIFY_URL")
    if not url:
        return ""
    url = url.split(",")[0].strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/") + "/"


def api(method, payload=None, timeout=20):
    req = urllib.request.Request(
        f"{setting('TELEGRAM_API') or 'https://api.telegram.org'}/bot{setting('TELEGRAM_TOKEN')}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        result = json.loads(r.read())
    if not result.get("ok"):
        raise ValueError("Telegram отклонил запрос")
    return result["result"]


def say(chat_id, text, button=True):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if button and page_url():
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Открыть ленту", "web_app": {"url": page_url()}}]]
        }
    return api("sendMessage", payload)


def setup(conn):
    me = api("getMe")
    if me["username"].casefold() != CONFIG["bot_username"].casefold():
        raise ValueError("Токен относится к другому боту; проверьте настройки приложения")
    api("setMyCommands", {"commands": COMMANDS})
    if page_url():
        api(
            "setChatMenuButton",
            {
                "menu_button": {
                    "type": "web_app",
                    "text": "Лента",
                    "web_app": {"url": page_url()},
                }
            },
        )
    else:
        api("setChatMenuButton", {"menu_button": {"type": "commands"}})
    db.log(SERVICE, f"@{me['username']}: сводка в 09:00 МСК")


def status_text(conn):
    lines = ["<b>Радар изменений</b> · 09:00 МСК\n", html.escape(coverage(conn))]
    for service, name in [("collector", "Сбор"), ("worker", "Анализ")]:
        run = conn.execute(
            "SELECT status,started_at,note FROM runs WHERE service=%s ORDER BY id DESC LIMIT 1",
            (service,),
        ).fetchone()
        if run:
            state = {
                "finished": "завершён",
                "failed": "ошибка",
                "started": "начат",
                "running": "идёт",
            }.get(run[0], run[0])
            lines.append(
                f"{name}: {state}, {run[1].astimezone(MSK):%d.%m %H:%M} МСК. "
                + html.escape(run[2] or "")
            )
    day = datetime.now(MSK).date()
    used = conn.execute(
        "SELECT coalesce(sum(coalesce(actual,reserved)),0) FROM radar_spend WHERE budget_day=%s",
        (day,),
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT count(*) FROM materials WHERE radar_version IS NOT NULL AND status IN ('new','failed','deferred')"
    ).fetchone()[0]
    ambiguous = conn.execute(
        "SELECT count(*) FROM radar_deliveries WHERE state IN ('sending','uncertain')"
    ).fetchone()[0]
    lines += [
        f"Бюджет сегодня: ${used:.4f} / ${Decimal(CONFIG['daily_budget_usd']):.2f}. Ожидают анализа: {pending}.",
        f"Доставок с неясным результатом: {ambiguous}.",
        html.escape(CONFIG["coverage_note"]),
    ]
    state = conn.execute("SELECT value FROM radar_meta WHERE key='analysis_state'").fetchone()
    if state:
        lines.append(html.escape(state[0]))
    return "\n".join(lines)


def handle(conn, message):
    chat = message["chat"]
    if chat.get("type") != "private":
        return
    words = (message.get("text") or "").split()
    command = words[0].split("@")[0] if words else ""
    if command == "/start":
        name = chat.get("username") or chat.get("first_name") or ""
        conn.execute(
            "INSERT INTO subscribers(chat_id,name) VALUES (%s,%s) ON CONFLICT(chat_id) DO UPDATE SET active=true",
            (chat["id"], name),
        )
        say(
            chat["id"],
            "Вы подписаны на радар изменений. Каждый день в 09:00 по Москве — до пяти важных событий и общий сигнал, если есть основания. "
            + (
                "Полные карточки и история — по кнопке «Открыть ленту». "
                if page_url()
                else "Полные карточки и история доступны в браузерной ленте радара. "
            )
            + "/status — состояние сбора и анализа.",
        )
    elif command == "/status":
        say(chat["id"], status_text(conn))
    else:
        say(
            chat["id"],
            "Команды: /start — подписка, /status — состояние. "
            + (
                "Карточки — по кнопке «Открыть ленту»."
                if page_url()
                else "Карточки доступны в браузерной ленте радара."
            ),
        )


def loop():
    while True:
        try:
            with db.connect() as conn:
                if not conn.execute("SELECT pg_try_advisory_lock(4215)").fetchone()[0]:
                    time.sleep(30)
                    continue
                setup(conn)
                last_send = 0
                while True:
                    offset = conn.execute(
                        "SELECT value FROM radar_meta WHERE key='telegram_offset'"
                    ).fetchone()
                    updates = api(
                        "getUpdates",
                        {
                            "timeout": 25,
                            "offset": int(offset[0]) if offset else None,
                            "allowed_updates": ["message"],
                        },
                        timeout=35,
                    )
                    for update in updates:
                        if "message" in update:
                            handle(conn, update["message"])
                        conn.execute(
                            "INSERT INTO radar_meta(key,value) VALUES ('telegram_offset',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (str(update["update_id"] + 1),),
                        )
                    if time.monotonic() - last_send > 45:
                        deliver(conn, say)
                        last_send = time.monotonic()
        except Exception as exc:
            # Never log Telegram request URLs: they embed the bot token.
            db.log(SERVICE, f"Ошибка связи: {type(exc).__name__}; повтор через 10 с")
            time.sleep(10)


def render_page(conn, archive=False):
    esc = html.escape
    header = """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Fintech Change Radar</title><style>body{font:16px/1.6 system-ui,sans-serif;background:#f6f5f1;color:#172b28;margin:0}main{max-width:880px;margin:auto;padding:24px 18px}article{background:white;padding:24px;margin:22px 0;border:1px solid #d6dcd5;border-radius:10px}a{color:#176b58}h1,h2,h3{line-height:1.25}h2{font-size:23px}h3{font-size:16px;margin-bottom:4px}p{margin-top:6px}.meta,small{color:#58655e}blockquote{margin:12px 0;padding-left:16px;border-left:3px solid #a6bbb1}nav{display:flex;gap:24px}</style><main>
    <h1>Радар изменений</h1><nav><a href="/">События</a><a href="/archive">Архив AI-находок</a></nav>"""
    parts = [header]
    if archive:
        parts.append(
            "<p>Архив прежнего проекта. Эти находки не участвуют в новом радаре и рассылках.</p>"
        )
        for summary, entity, url in conn.execute(
            "SELECT f.summary,f.entity,m.url FROM findings f JOIN materials m ON m.id=f.material_id ORDER BY f.id DESC LIMIT 300"
        ):
            parts.append(
                f'<article><h2>{esc(entity or "Без компании")}</h2><p>{esc(summary)}</p><a href="{esc(url, quote=True)}" rel="noopener noreferrer">Источник</a></article>'
            )
    else:
        parts.append(
            "<p>" + esc(CONFIG["coverage_note"]) + "</p><p>" + esc(coverage(conn)) + "</p>"
        )
        events = event_rows(
            conn,
            "WHERE e.created_at>now()-interval '60 days' ORDER BY e.id DESC LIMIT 300",
        )
        common = signal(events)
        if common:
            parts.append(
                "<article><h2>Общий сигнал</h2><p>"
                + esc(common["text"])
                + "</p><p>Основания: "
                + ", ".join(f'<a href="#{i}">Событие №{i}</a>' for i in common["event_ids"])
                + "</p></article>"
            )
        if not events:
            parts.append(
                "<p>Карточек пока нет. Сбор и анализ могут продолжаться; состояние доступно через /status в боте.</p>"
            )
        for e in events:
            c = e["card"]
            eid = e["id"]
            parts.append(
                f'<article id="{eid}"><small>Событие №{eid} · {"История" if e["historical"] else "Новое событие"}</small><h2>{esc(c["title"])}</h2><p class="meta">{esc(e["company"])} · {esc(c["market"])} · {e["event_date"] or "Дата события не установлена"} · {esc(c["change_type"])}</p>'
            )
            if not common or eid not in common["event_ids"]:
                parts.append(
                    '<p class="meta">Ранний сигнал: отдельное событие; распространение механики не подтверждено.</p>'
                )
            for label, key in [
                ("Подтверждённые факты", "facts"),
                ("Что это может значить для банка", "interpretation"),
                ("Гипотеза для проверки", "hypothesis"),
                ("Ограничения и неопределённость", "limitations"),
                ("Исследовательский вопрос", "research_question"),
            ]:
                parts.append(f"<h3>{label}</h3><p>{esc(c[key])}</p>")
            parts.append(
                "<p><b>Рекомендация:</b> " + esc(c["recommendation"]) + "</p><h3>Основания</h3>"
            )
            for url, title, quote, mode in conn.execute(
                "SELECT m.url,m.title,v.quote,m.content_mode FROM radar_evidence v JOIN materials m ON m.id=v.material_id WHERE v.event_id=%s ORDER BY m.id",
                (eid,),
            ):
                parts.append(
                    f'<p><a href="{esc(url, quote=True)}" rel="noopener noreferrer">{esc(title)}</a><br><small>{esc(mode)}</small></p><blockquote>{esc(quote)}</blockquote>'
                )
            parts.append(
                f"<small>Модель: {esc(e['model'])} · Правила: {esc(e['rules_version'])}</small></article>"
            )
    return "".join(parts) + "</main></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            with db.connect() as conn:
                if path == "/health":
                    conn.execute("SELECT 1")
                    body, code, kind = b"ok", 200, "text/plain"
                elif path in ("/", "/archive"):
                    body, code, kind = (
                        render_page(conn, path == "/archive").encode(),
                        200,
                        "text/html; charset=utf-8",
                    )
                else:
                    body, code, kind = b"not found", 404, "text/plain"
        except Exception:
            body, code, kind = (
                "Лента временно недоступна".encode(),
                503,
                "text/plain; charset=utf-8",
            )
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    with db.connect() as conn:
        db.init_schema(conn)
    if setting("TELEGRAM_TOKEN"):
        threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
