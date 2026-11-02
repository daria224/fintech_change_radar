"""Save visible conversation, tracked source, Git history and local DB, without secrets."""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def export_conversation(source, output):
    raw = source.read_bytes()
    messages = []
    records = 0
    partial = 0
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1 and not raw.endswith(b"\n"):
                partial += 1
                continue
            raise
        records += 1
        payload = record.get("payload", {})
        if record.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            continue
        if payload.get("channel") not in (None, "commentary", "final"):
            continue
        if payload.get("role") == "assistant" and payload.get("phase") not in (
            "commentary",
            "final_answer",
            None,
        ):
            continue
        parts = [
            part.get("text", "")
            for part in payload.get("content", [])
            if part.get("type") in ("input_text", "output_text")
        ]
        text = "\n\n".join(parts)
        if text:
            messages.append(
                {
                    "timestamp": record.get("timestamp"),
                    "role": payload["role"],
                    "phase": payload.get("phase"),
                    "text": text,
                }
            )
    info = {
        "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_records_read": records,
        "source_bytes_read": len(raw),
        "incomplete_last_record_skipped": partial,
        "message_counts": dict(Counter(m["role"] for m in messages)),
        "scope": "Все доступные пользовательские сообщения и видимые ответы/обновления ассистента на момент сохранения. Системные инструкции, внутренние рассуждения и технические вызовы инструментов не экспортируются. Результаты инструментов сохранены отдельно в коде, отчётах и скриншотах.",
        "messages": messages,
    }
    (output / "SESSION_TRANSCRIPT.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = "# Переписка Fintech Change Radar\n\n" + info["scope"] + "\n\n"
    for message in messages:
        title = "Пользователь" if message["role"] == "user" else "Ассистент"
        md += f"## {title} · {message['timestamp']}\n\n{message['text']}\n\n---\n\n"
        if (
            message["role"] == "user"
            and "Fintech Change Radar — план реализации" in message["text"]
        ):
            (output / "ORIGINAL_PLAN.md").write_text(message["text"], encoding="utf-8")
    (output / "SESSION_TRANSCRIPT.md").write_text(md, encoding="utf-8")
    return {k: v for k, v in info.items() if k != "messages"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--backup-local-db", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = ROOT.parent / ("SESSION_SAVE_" + stamp)
    output.mkdir()
    info = export_conversation(args.session_file, output)
    head = run(["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE, text=True).stdout.strip()
    tracked = (
        run(["git", "ls-files", "-z"], stdout=subprocess.PIPE).stdout.decode("utf-8").split("\0")
    )
    source_zip = output / "radar_source.zip"
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in filter(None, tracked):
            path = ROOT / name
            if path.is_file():
                if path.name == ".env.local" or path.suffix == ".dump":
                    raise RuntimeError("Private file unexpectedly tracked; export stopped")
                archive.write(path, "radar/" + name)
    with zipfile.ZipFile(source_zip) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Source ZIP failed CRC validation")
    bundle = output / "radar_git_history.bundle"
    run(["git", "bundle", "create", str(bundle), "--all"])
    run(["git", "bundle", "verify", str(bundle)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    shutil.copy2(ROOT / "HANDOFF.md", output / "START_HERE.md")
    shots = output / "screenshots"
    shots.mkdir()
    for path in ROOT.parent.glob("*.png"):
        shutil.copy2(path, shots / path.name)
    backup = None
    if args.backup_local_db:
        compose = [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env.local"),
            "-f",
            str(ROOT / "compose.local.yaml"),
        ]
        try:
            run(compose + ["up", "-d", "--no-deps", "--wait", "postgres"])
            backup = output / "local_database.dump"
            with backup.open("xb") as stream:
                run(
                    compose
                    + [
                        "exec",
                        "-T",
                        "postgres",
                        "pg_dump",
                        "-U",
                        "radar_local",
                        "-d",
                        "fintech_radar",
                        "-Fc",
                    ],
                    stdout=stream,
                )
            with backup.open("rb") as stream:
                run(
                    compose + ["exec", "-T", "postgres", "pg_restore", "--file=/dev/null"],
                    stdin=stream,
                )
            stats = run(
                compose
                + [
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "radar_local",
                    "-d",
                    "fintech_radar",
                    "-At",
                    "-c",
                    "SELECT json_build_object('materials',(SELECT count(*) FROM materials),'events',(SELECT count(*) FROM radar_events),'paid_requests',(SELECT count(*) FROM radar_spend),'subscribers',(SELECT count(*) FROM subscribers));",
                ],
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            info["local_database_counts"] = json.loads(stats)
        finally:
            run(compose + ["stop", "postgres"])
    info.update(
        {
            "head": head,
            "branch": "fintech-change-radar",
            "local_database_backup": backup.name if backup else None,
            "secrets": "Файл .env.local исключён; остался только в рабочей папке. Серверные секреты и серверная база не копировались.",
            "source_zip_crc_ok": True,
            "git_bundle_verified": True,
        }
    )
    (output / "snapshot.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    instructions = """# Сохранённая сессия и результаты

Начните с START_HERE.md — там текущее решение, состояние кода, проверки и шаги продолжения через GitHub и Coolify.

- SESSION_TRANSCRIPT.md / .json — переписка на момент сохранения.
- ORIGINAL_PLAN.md — исходный план задачи.
- radar_source.zip — исходники, инструкции, результаты проверок и альтернативные способы запуска. Секретов и виртуального окружения нет.
- radar_git_history.bundle — вся локальная история Git. Восстановление: git clone radar_git_history.bundle radar-restored; затем git switch fintech-change-radar.
- local_database.dump — отдельная локальная база с собранными публикациями; это не рабочая база Coolify. Дамп проверен чтением pg_restore; развёртывание в отдельную БД пока не проверялось.
- screenshots/ — скриншоты задания и Coolify.
- snapshot.json и SHA256SUMS.txt — состав и контрольные суммы.

Рабочая папка radar остаётся на прежнем месте. Локальные bot и worker остановлены. Старое приложение Coolify не обновлялось и не останавливалось агентом. Архив локальный: в GitHub ничего не отправлено. Файл .env.local в архив не включён.

Для нового агента: «Открой START_HERE.md в этой папке и продолжи путь через GitHub → существующее приложение Coolify. Локальный бот не запускай». Не загружайте резервную копию базы и личную переписку в публичный репозиторий.
"""
    (output / "README.md").write_text(instructions, encoding="utf-8")
    checks = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            checks.append(
                hashlib.sha256(path.read_bytes()).hexdigest()
                + "  "
                + path.relative_to(output).as_posix()
            )
    (output / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
    for line in checks:
        expected, name = line.split("  ", 1)
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Checksum verification failed: " + name)
    print(
        json.dumps(
            {
                "saved_to": str(output),
                "verified_files": len(checks),
                "messages": info["message_counts"],
                "head": head,
                "local_database_counts": info.get("local_database_counts"),
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
