import os
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from radar_core.analysis import analyze, candidate, reserve, validate
from radar_core.collect import article, canonical_url, collectable, entries, plain
from radar_core.config import CONFIG, MSK
from radar_core.digest import build, deliver, select_events, signal

TEXT = "Банк запустил переводы по номеру телефона без комиссии для всех клиентов."


def card(company="Тест Банк"):
    return dict(
        relevant=True,
        company=company,
        market="Россия",
        event_date="2026-11-01",
        identity="переводы по телефону",
        title="Банк запустил переводы по телефону",
        change_type="функция",
        mechanism="платежи",
        pattern="переводы по номеру телефона без комиссии",
        facts=TEXT,
        interpretation="Сценарий может уменьшить число шагов при переводе.",
        hypothesis="Клиенты смогут быстрее отправлять деньги.",
        limitations="Не установлены лимиты и условия доступности. Требуется проверка в РФ.",
        research_question="Как меняются время перевода и число ошибок?",
        recommendation="исследовать",
        quote=TEXT,
        applicability=2,
        novelty=2,
        evidence=2,
        urgency=1,
        existing_event_id=None,
    )


def event(eid, company="Тест Банк", pattern=None, mechanism="платежи"):
    c = card(company)
    if pattern is not None:
        c["pattern"] = pattern
    return dict(id=eid, company=company, card=c, mechanism=mechanism, quote=TEXT + company)


class PureTests(unittest.TestCase):
    def test_url_and_html(self):
        self.assertEqual(
            canonical_url("https://EXAMPLE.com/a?utm_source=x&b=2#top"),
            "https://example.com/a?b=2",
        )
        with self.assertRaises(ValueError):
            canonical_url("javascript:alert(1)")
        self.assertEqual(plain("<p>Привет &amp; мир</p><script>bad()</script>"), "Привет & мир")

    def test_rss_atom_and_invalid_dates(self):
        rss = b"<rss><channel><item><title>A</title><link>https://example.com/a</link><pubDate>bad</pubDate><description>&lt;p&gt;Text&lt;/p&gt;</description></item></channel></rss>"
        x = list(entries(rss))[0]
        self.assertIsNone(x["published_at"])
        self.assertEqual(x["text"], "Text")
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><link href="https://example.com/b"/><updated>2026-11-01T09:00:00Z</updated><summary>body</summary></entry></feed>'
        self.assertEqual(list(entries(atom))[0]["published_at"].hour, 9)

    def test_article_failure_is_explicit(self):
        with patch("radar_core.collect.fetch", side_effect=TimeoutError):
            text, mode = article("https://example.com", "описание")
        self.assertEqual(text, "описание")
        self.assertIn("недоступен", mode)

    def test_collection_keeps_source_history_without_age_cutoff(self):
        now = datetime(2026, 11, 5)
        self.assertTrue(collectable(now - timedelta(days=365), now))
        self.assertFalse(collectable(now + timedelta(days=1), now))
        self.assertTrue(collectable(None, now))

    def test_telegram_polling_requires_explicit_enable_and_token(self):
        from bot.main import telegram_enabled

        with patch.dict(
            os.environ,
            {"TELEGRAM_ENABLED": "false", "TELEGRAM_TOKEN": "test-only"},
        ):
            self.assertFalse(telegram_enabled())
        with patch.dict(
            os.environ,
            {"TELEGRAM_ENABLED": "true", "TELEGRAM_TOKEN": ""},
        ):
            self.assertFalse(telegram_enabled())
        with patch.dict(
            os.environ,
            {"TELEGRAM_ENABLED": "true", "TELEGRAM_TOKEN": "test-only"},
        ):
            self.assertTrue(telegram_enabled())

    def test_openrouter_requires_explicit_opt_in(self):
        from radar_core.analysis import AnalysisPaused

        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "false", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch("radar_core.analysis.prices") as prices,
            patch("radar_core.analysis.request_json") as request,
        ):
            with self.assertRaises(AnalysisPaused):
                analyze(None, "title", "text", None, "описание", [])
            prices.assert_not_called()
            request.assert_not_called()

    def test_openrouter_requires_a_configured_model(self):
        from radar_core.analysis import AnalysisPaused

        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch("radar_core.analysis.MODEL", ""),
            patch("radar_core.analysis.prices") as prices,
        ):
            with self.assertRaises(AnalysisPaused):
                analyze(None, "title", "text", None, "описание", [])
            prices.assert_not_called()

    def test_20_labeled_prefilter_cases(self):
        # Synthetic boundary cases, not a claim of live-model quality.
        cases = [
            ("Банк запустил переводы", True),
            ("OpenAI introduces a new assistant", True),
            ("Регулирование платежей изменится", True),
            ("Revolut launches travel insurance", True),
            ("Сервис закрывает приложение", True),
            ("Новый тариф банка", True),
            ("Новый интерфейс приложения", True),
            ("Kaspi запустил пилот", True),
            ("Stripe acquires a startup", True),
            ("Партнёрство TBC и магазина", True),
            ("Курс доллара на сегодня", False),
            ("Курсы валют утром", False),
            ("Гороскоп на неделю", False),
            ("Котировки акций", False),
            ("Прогноз погоды", False),
            ("Как правильно заваривать чай", False),
            ("Мнение автора о будущем", False),
            ("История искусства", False),
            ("Наши праздничные поздравления", False),
            ("Биржевые итоги дня", False),
        ]
        for title, label in cases:
            with self.subTest(title=title):
                self.assertEqual(candidate(title, ""), label)

    def test_validation_and_grounding(self):
        self.assertTrue(validate(card(), TEXT, [])["relevant"])
        for field, value in [
            ("facts", "English only"),
            ("quote", "Такого утверждения нет в тексте вообще."),
            ("applicability", True),
            ("existing_event_id", 10),
        ]:
            c = card()
            c[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(c, TEXT, [])

    def test_merge_cannot_cross_companies(self):
        c = card()
        c["existing_event_id"] = 1
        with self.assertRaises(ValueError):
            validate(c, TEXT, [{"id": 1, "company": "Другой Банк"}])

    def test_signal_requires_events_companies_and_different_evidence(self):
        self.assertIsNone(signal([event(1)]))
        self.assertIsNone(signal([event(1), event(2)]))
        self.assertIsNotNone(signal([event(1), event(2, "Другой Банк")]))
        a, b = event(1), event(2, "Другой Банк")
        b["quote"] = a["quote"]
        self.assertIsNone(signal([a, b]))
        self.assertIsNone(
            signal(
                [
                    event(1, pattern="платежи"),
                    event(2, "Другой Банк", pattern="платежи"),
                ]
            )
        )

    def test_diversity_and_no_padding(self):
        a, b, c = event(1), event(2), event(3, mechanism="кредитование")
        self.assertEqual([e["id"] for e in select_events([a, b, c])], [1, 3, 2])
        self.assertEqual(len(select_events([a])), 1)

    def test_unknown_price_never_calls_paid_endpoint(self):
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch("radar_core.analysis.prices", side_effect=ValueError("unknown")),
            patch("radar_core.analysis.request_json") as call,
        ):
            with self.assertRaises(ValueError):
                analyze(None, "title", "text", None, "описание", [])
            call.assert_not_called()

    def test_wrong_bot_identity_is_rejected_before_changes(self):
        from bot.main import setup

        with patch("bot.main.api", return_value={"username": "another_bot"}) as api:
            with self.assertRaises(ValueError):
                setup(None)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.args[0], "getMe")


@unittest.skipUnless(os.environ.get("RADAR_TEST_DATABASE_URL"), "Requires isolated test Postgres")
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.conn = psycopg.connect(os.environ["RADAR_TEST_DATABASE_URL"], autocommit=True)
        if cls.conn.info.dbname != "radar_test":
            raise RuntimeError("Only radar_test database is allowed")
        import db

        db.init_schema(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.conn.execute(
            "TRUNCATE radar_deliveries,radar_digests,radar_evidence,radar_events,radar_spend,radar_source_checks,materials,findings,runs,subscribers,radar_jobs RESTART IDENTITY CASCADE"
        )
        self.conn.execute(
            "DELETE FROM radar_meta WHERE key IN ('collection_initialized','backfill_done','billing_pause')"
        )

    def material(self, historical=False):
        sid = self.conn.execute("SELECT id FROM sources WHERE active LIMIT 1").fetchone()[0]
        return self.conn.execute(
            "INSERT INTO materials(source_id,url,title,text,published_at,radar_version,historical) VALUES (%s,%s,%s,%s,now(),%s,%s) RETURNING id",
            (
                sid,
                "https://example.com/"
                + str(self.conn.execute("SELECT count(*) FROM materials").fetchone()[0]),
                "Банк запустил переводы",
                TEXT,
                CONFIG["rules_version"],
                historical,
            ),
        ).fetchone()[0]

    def test_repeatable_migration_preserves_legacy_and_subscribers(self):
        import db

        mid = self.material()
        self.conn.execute(
            "INSERT INTO findings(material_id,summary,model,prompt_version) VALUES (%s,'архив','old','v1')",
            (mid,),
        )
        self.conn.execute("INSERT INTO subscribers(chat_id,name) VALUES (42,'Старый подписчик')")
        db.init_schema(self.conn)
        db.init_schema(self.conn)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM findings").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT chat_id FROM subscribers").fetchone()[0], 42)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM sources WHERE active").fetchone()[0],
            10,
        )

    def test_budget_is_shared_and_persistent(self):
        self.assertIsNotNone(reserve(self.conn, Decimal(".7")))
        self.assertIsNone(reserve(self.conn, Decimal(".4")))
        self.assertIsNotNone(reserve(self.conn, Decimal(".3")))
        self.assertIsNone(reserve(self.conn, Decimal(".001")))

    def test_concurrent_budget_reservations(self):
        from concurrent.futures import ThreadPoolExecutor

        import psycopg

        def take(_):
            with psycopg.connect(os.environ["RADAR_TEST_DATABASE_URL"], autocommit=True) as other:
                return reserve(other, Decimal(".3"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            reservations = list(pool.map(take, range(8)))
        self.assertEqual(sum(x is not None for x in reservations), 3)
        used = self.conn.execute("SELECT sum(reserved) FROM radar_spend").fetchone()[0]
        self.assertEqual(used, Decimal(".9"))

    def test_no_key_defers_without_spending_or_consuming_retries(self):
        from radar_core.analysis import process

        mid = self.material()
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": ""},
            ),
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
        ):
            process(self.conn)
        row = self.conn.execute(
            "SELECT status,attempts FROM materials WHERE id=%s", (mid,)
        ).fetchone()
        self.assertEqual(row, ("deferred", 0))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM radar_spend").fetchone()[0], 0)

    def test_malformed_response_is_charged_and_rejected(self):
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch(
                "radar_core.analysis.prices",
                return_value=(Decimal(".0000004"), Decimal(".0000016")),
            ),
            patch(
                "radar_core.analysis.request_json",
                return_value={
                    "usage": {"cost": ".001"},
                    "choices": [{"message": {"content": "not JSON"}}],
                },
            ),
        ):
            with self.assertRaises(ValueError):
                analyze(self.conn, "test", TEXT, None, "описание", [])
        self.assertEqual(
            self.conn.execute("SELECT actual FROM radar_spend").fetchone()[0],
            Decimal(".001"),
        )

    def test_missing_cost_retains_upper_bound(self):
        response = {"choices": [{"message": {"content": '{"relevant":false}'}}]}
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch(
                "radar_core.analysis.prices",
                return_value=(Decimal(".0000004"), Decimal(".0000016")),
            ),
            patch("radar_core.analysis.request_json", return_value=response),
        ):
            self.assertFalse(analyze(self.conn, "test", TEXT, None, "описание", [])["relevant"])
        row = self.conn.execute("SELECT state,actual,reserved FROM radar_spend").fetchone()
        self.assertEqual(row[0], "charged_upper_bound")
        self.assertIsNone(row[1])
        self.assertGreater(row[2], 0)

    def test_collection_schedule_runs_once_per_slot(self):
        from worker.main import tick

        with patch("worker.main.collect") as collect, patch("worker.main.process"):
            tick(self.conn)
            tick(self.conn)
        self.assertEqual(collect.call_count, 1)
        self.assertTrue(collect.call_args.kwargs["historical"])

    def test_bot_start_preserves_subscription_and_status(self):
        from bot.main import handle, status_text

        with patch("bot.main.say") as say:
            handle(
                self.conn,
                {
                    "chat": {"id": 55, "type": "private", "first_name": "Читатель"},
                    "text": "/start",
                },
            )
            handle(
                self.conn,
                {
                    "chat": {"id": 55, "type": "private", "first_name": "Читатель"},
                    "text": "/start",
                },
            )
        self.assertEqual(self.conn.execute("SELECT count(*) FROM subscribers").fetchone()[0], 1)
        self.assertIn("Бюджет", status_text(self.conn))
        self.assertEqual(say.call_count, 2)

    def test_paid_error_keeps_reservation(self):
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_ENABLED": "true", "OPENROUTER_API_KEY": "test-only"},
            ),
            patch(
                "radar_core.analysis.prices",
                return_value=(Decimal(".000001"), Decimal(".000002")),
            ),
            patch("radar_core.analysis.request_json", side_effect=TimeoutError),
        ):
            with self.assertRaises(TimeoutError):
                analyze(self.conn, "title", TEXT, None, "описание", [])
        row = self.conn.execute("SELECT reserved,actual,state FROM radar_spend").fetchone()
        self.assertGreater(row[0], 0)
        self.assertIsNone(row[1])
        self.assertEqual(row[2], "uncertain")

    def test_collection_repeat_history_and_source_failures(self):
        from radar_core.collect import collect

        feed = [
            dict(
                url="https://example.com/news",
                title="Банк запустил переводы",
                text=TEXT,
                published_at=datetime.now(MSK),
            )
        ]
        with (
            patch("radar_core.collect.fetch", return_value=b"fixture"),
            patch("radar_core.collect.entries", return_value=iter(feed)),
        ):
            collect(self.conn)
        with patch("radar_core.collect.fetch", side_effect=TimeoutError):
            collect(self.conn)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM materials").fetchone()[0], 1)
        self.assertTrue(self.conn.execute("SELECT historical FROM materials").fetchone()[0])
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM radar_source_checks WHERE NOT ok").fetchone()[
                0
            ],
            10,
        )

    def test_chain_merge_feed_and_legacy_isolation(self):
        from bot.main import render_page
        from radar_core.analysis import process

        self.material()
        self.material()
        one = card()
        two = card()
        two["existing_event_id"] = 1
        with (
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
            patch("radar_core.analysis.analyze", side_effect=[one, two]),
        ):
            self.assertEqual(process(self.conn), 2)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM radar_events").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM radar_evidence").fetchone()[0], 2)
        page = render_page(self.conn)
        self.assertIn("Что это может значить для банка", page)
        self.assertIn("Исследовательский вопрос", page)
        self.assertNotIn("Старый AI", page)
        self.assertEqual(process(self.conn), 0)

    def test_bad_model_and_deferred_budget(self):
        from radar_core.analysis import process

        mid = self.material()
        with (
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
            patch("radar_core.analysis.analyze", side_effect=ValueError("invalid JSON")),
        ):
            process(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT attempts FROM materials WHERE id=%s", (mid,)).fetchone()[0],
            1,
        )
        self.conn.execute("UPDATE materials SET retry_at=NULL WHERE id=%s", (mid,))
        with (
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
            patch("radar_core.analysis.analyze", return_value=None),
        ):
            process(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT status FROM materials WHERE id=%s", (mid,)).fetchone()[0],
            "deferred",
        )

    def test_digest_clock_snapshot_and_recipient_restart(self):
        now = datetime.now(MSK).replace(hour=9, minute=0, second=0, microsecond=0)
        self.conn.execute("INSERT INTO subscribers(chat_id) VALUES (1),(2)")
        self.assertIsNone(build(self.conn, now - timedelta(seconds=1)))
        sent = []

        def send(chat, text):
            sent.append(chat)
            if chat == 2:
                raise TimeoutError()
            return {"message_id": 99}

        deliver(self.conn, send, now)
        deliver(self.conn, send, now)
        self.assertEqual(sent, [1, 2])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM radar_digests").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM radar_deliveries WHERE state='uncertain'"
            ).fetchone()[0],
            1,
        )
        self.assertIn("пока нет", build(self.conn, now)[1])

    def test_history_never_becomes_fresh(self):
        from radar_core.analysis import process

        self.material(True)
        with (
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
            patch("radar_core.analysis.analyze", return_value=card()),
        ):
            process(self.conn)
        now = datetime.now(MSK).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        build(self.conn, now)
        self.assertEqual(self.conn.execute("SELECT event_ids FROM radar_digests").fetchone()[0], [])

    def test_fresh_event_enters_digest_once(self):
        from radar_core.analysis import process

        self.material()
        with (
            patch("radar_core.analysis.article", return_value=(TEXT, "описание")),
            patch("radar_core.analysis.analyze", return_value=card()),
        ):
            process(self.conn)
        now = datetime.now(MSK).replace(hour=9, minute=0, second=0, microsecond=0)
        self.conn.execute("UPDATE radar_events SET created_at=%s", (now - timedelta(minutes=30),))
        self.conn.execute("UPDATE materials SET published_at=%s", (now - timedelta(hours=1),))
        build(self.conn, now)
        self.assertEqual(
            self.conn.execute("SELECT event_ids FROM radar_digests").fetchone()[0], [1]
        )
        build(self.conn, now + timedelta(days=1))
        self.assertEqual(
            self.conn.execute(
                "SELECT event_ids FROM radar_digests ORDER BY day DESC LIMIT 1"
            ).fetchone()[0],
            [],
        )

    def test_blocked_and_rate_limited_delivery(self):
        from urllib.error import HTTPError

        now = datetime.now(MSK).replace(hour=9, minute=0, second=0, microsecond=0)
        self.conn.execute("INSERT INTO subscribers(chat_id) VALUES (1),(2),(3)")

        def send(chat, text):
            if chat == 1:
                raise HTTPError("https://telegram.invalid", 403, "blocked", None, None)
            if chat == 2:
                raise HTTPError("https://telegram.invalid", 429, "slow", None, None)

        deliver(self.conn, send, now)
        self.assertFalse(
            self.conn.execute("SELECT active FROM subscribers WHERE chat_id=1").fetchone()[0]
        )
        states = dict(self.conn.execute("SELECT chat_id,state FROM radar_deliveries").fetchall())
        self.assertEqual(states, {1: "blocked", 2: "pending", 3: "pending"})
        deliver(self.conn, lambda chat, text: {"message_id": chat}, now)
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) FROM radar_deliveries WHERE state='sent'"
            ).fetchone()[0],
            2,
        )

    def test_http_feed_and_health_without_bot_token(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from bot.main import Handler

        with patch.dict(os.environ, {"DATABASE_URL": os.environ["RADAR_TEST_DATABASE_URL"]}):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for path in ("/health", "/", "/archive"):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}{path}"
                    ) as response:
                        self.assertEqual(response.status, 200)
                        body = response.read().decode()
                        self.assertTrue(body)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
