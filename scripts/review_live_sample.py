"""Record human review of the captured 20-item snapshot; no model is invoked."""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from radar_core.analysis import candidate

# These annotations refer only to the snapshot captured on 2026-11-02.
# 'review' deliberately leaves uncertain article-level relevance unresolved.
LABELS = {
    "11028641": (
        "review",
        "Статистика кредитов; описание упоминает ужесточение требований, но конкретное изменение продукта не установлено.",
    ),
    "11028637": ("exclude", "Обменные курсы и сравнение котировок, без продуктового изменения."),
    "639292076474400194COINS": (
        "exclude",
        "Выпуск памятной монеты без установленной связи с цифровым банковским продуктом.",
    ),
    "639289575398220007SITE": (
        "exclude",
        "Кратковременные работы на сайте регулятора; существенное изменение доступа клиентов не установлено.",
    ),
    "1102696": ("exclude", "Обучающая статья о расчётах, не сообщение о новом изменении."),
    "1102652": (
        "review",
        "Тема страхования AI-рисков перспективна; нужен полный текст для проверки конкретных новых продуктов.",
    ),
    "48683": (
        "include",
        "Конкретный инцидент безопасности и реакция клиентов; применим к исследованию доверия.",
    ),
    "48682": (
        "include",
        "Отмена IPO после регуляторной проверки: конкретное стратегическое событие финтех-компании.",
    ),
    "omen-ai-adds": (
        "exclude",
        "Сделка в охлаждении дата-центров; в доступном описании нет конкретной связи с клиентским продуктом банка.",
    ),
    "ninjas-first-ever": ("exclude", "Бытовая техника без установленной банковской применимости."),
    "/913609/": ("exclude", "Выручка фитнес-клубов без существенного нового цифрового сценария."),
    "/914165/": ("exclude", "Открытие ресторана без релевантного цифрового изменения."),
    "grid-protectors-program": (
        "review",
        "Новая программа требует проверки полного текста; связь с продуктовой стратегией банка не установлена по заголовку.",
    ),
    "helping-websites-express": (
        "include",
        "Новый механизм управления предпочтениями использования данных: доступ и доверие.",
    ),
    "fitbit-edge": (
        "exclude",
        "Аппаратный фитнес-трекер; из доступного описания не следует существенный переносимый банковский сценарий.",
    ),
    "project-suncatcher": (
        "exclude",
        "Исследовательский спутник; клиентское изменение для банка не установлено.",
    ),
    "lavenir-appartient": (
        "include",
        "Новое партнёрство по доступности. Перевод того же события Meta/CNIB, не независимый сигнал.",
    ),
    "the-future-is-for-everyone": (
        "include",
        "Партнёрство и поддержка пользователей с нарушениями зрения; тема исследования доступности.",
    ),
    "introducing-the-microsoft-copilot": (
        "include",
        "Запуск инструмента оркестрации нескольких моделей; конкретная основа для проверки сценариев помощника.",
    ),
    "the-platform-approach": (
        "exclude",
        "Общая концептуальная статья; новое изменение не установлено по доступному описанию.",
    ),
}


def main():
    report = json.loads((root / "reports/live_sources.json").read_text(encoding="utf-8"))
    reviewed = []
    for source in report["sources"]:
        for item in source.get("sample", []):
            match = next((v for k, v in LABELS.items() if k in item["url"]), None)
            if not match:
                raise SystemExit(
                    "Неизвестный материал; снимок изменился. Нужна новая ручная разметка: "
                    + item["url"]
                )
            reviewed.append(
                dict(
                    source=source["name"],
                    title=item["title"],
                    url=item["url"],
                    decision=match[0],
                    reason=match[1],
                    prefilter=candidate(item["title"], item["text"]),
                )
            )
            item["text"] = item["text"][:350]
    if len(reviewed) != 20:
        raise SystemExit("Ожидалось 20 материалов")
    included = [x for x in reviewed if x["decision"] == "include"]
    result = {
        "snapshot_at": report["checked_at"],
        "scope": "Ручная разметка заголовков и доступных описаний, проверка предварительного фильтра. Это не оценка живой модели или готовых карточек.",
        "reviewer": "Codex, ручной разбор доступного снимка",
        "include": len(included),
        "retained_by_prefilter": sum(x["prefilter"] for x in included),
        "requires_full_text": sum(x["decision"] == "review" for x in reviewed),
        "duplicate_note": "Две публикации Meta на разных языках описывают одно событие и не подтверждают распространение механики.",
        "materials": reviewed,
    }
    (root / "reports/live_sample_review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "reports/live_sources.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Reviewed: 20; included for analysis: {len(included)}; retained: {result['retained_by_prefilter']}; unresolved: {result['requires_full_text']}"
    )


if __name__ == "__main__":
    main()
