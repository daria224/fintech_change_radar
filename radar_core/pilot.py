"""Explicit, ID-scoped OpenRouter pilot; never invoked by the worker schedule."""

import argparse

import db
from radar_core.analysis import candidate, process


def eligible(conn, limit=20):
    rows = conn.execute(
        """SELECT id,title,published_at,status FROM materials
           WHERE radar_version IS NOT NULL AND status IN ('new','deferred','failed')
             AND attempts<3 AND NOT analysis_retry_blocked
             AND (retry_at IS NULL OR retry_at<=now())
           ORDER BY historical,published_at DESC NULLS LAST,id LIMIT %s""",
        (limit * 3,),
    ).fetchall()
    return [row for row in rows if candidate(row[1], "")][:limit]


def parse_ids(value):
    try:
        ids = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID должны быть целыми числами через запятую") from exc
    if len(ids) not in (3, 4, 5) or any(material_id <= 0 for material_id in ids):
        raise argparse.ArgumentTypeError("Укажите от 3 до 5 положительных ID публикаций")
    if len(ids) != len(set(ids)):
        raise argparse.ArgumentTypeError("ID не должны повторяться")
    return ids


def report_results(conn, ids):
    spend_rows = conn.execute(
        """SELECT material_id,
                  count(*) FILTER (WHERE request_started_at IS NOT NULL),
                  coalesce(sum(actual),0),
                  coalesce(sum(reserved) FILTER (WHERE actual IS NULL),0),
                  coalesce(string_agg(DISTINCT state, ',' ORDER BY state),'none')
           FROM radar_spend WHERE pilot=true AND material_id=ANY(%s)
           GROUP BY material_id""",
        (ids,),
    ).fetchall()
    spend = {row[0]: row[1:] for row in spend_rows}
    rows = conn.execute(
        """SELECT id,status,attempts,last_analysis_stage,last_analysis_reason
           FROM materials WHERE id=ANY(%s) ORDER BY id""",
        (ids,),
    ).fetchall()
    for material_id, status, attempts, stage, reason in rows:
        calls, actual, held, states = spend.get(material_id, (0, 0, 0, "none"))
        print(
            f"ID {material_id}: status={status}; stage={stage or 'unknown'}; "
            f"attempts={attempts}; OpenRouter calls started={calls}; "
            f"actual_cost=${actual}; unresolved_reserve=${held}; spend_states={states}; "
            f"reason={reason or 'нет'}"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Показать кандидатов без AI-вызовов")
    group.add_argument("--ids", type=parse_ids, help="Явно выбрать 3–5 ID для платного пилота")
    args = parser.parse_args(argv)

    with db.connect() as conn:
        db.init_schema(conn)
        if args.list:
            for material_id, title, published, status in eligible(conn):
                print(f"{material_id}\t{published or 'дата неизвестна'}\t{status}\t{title[:180]}")
            return

        selected = set(args.ids)
        rows = conn.execute(
            """SELECT id,title FROM materials
               WHERE id=ANY(%s) AND radar_version IS NOT NULL
                 AND status IN ('new','deferred','failed') AND attempts<3
                 AND NOT analysis_retry_blocked
                 AND (retry_at IS NULL OR retry_at<=now())""",
            (args.ids,),
        ).fetchall()
        eligible_rows = {row[0]: row[1] for row in rows if candidate(row[1], "")}
        if set(eligible_rows) != selected:
            missing = ",".join(str(item) for item in sorted(selected - set(eligible_rows)))
            raise SystemExit(f"Пилот остановлен: ID не готовы к обработке: {missing}")
        print(f"Пилот: {len(args.ids)} выбранных публикаций; общий лимит расходов $1.00.")
        found = process(conn, limit=len(args.ids), material_ids=args.ids, pilot=True)
        report_results(conn, args.ids)
        print(f"Пилот завершён; создано или обновлено событий: {found}.")


if __name__ == "__main__":
    main()
