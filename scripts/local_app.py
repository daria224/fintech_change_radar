"""Local desktop launch. Secrets stay in .env.local and never enter CLI arguments."""

import argparse
import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
DEFAULTS = {
    "MODEL": "openai/gpt-4.1-mini",
    "TELEGRAM_TOKEN": "",
    "OPENROUTER_API_KEY": "",
    "MINI_APP_URL": "",
    "LOCAL_FEED_PORT": "18080",
    "SERVER_INSTANCE_STOPPED": "no",
}


def read_settings():
    settings = dict(DEFAULTS)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip()
    return settings


def save_settings(settings):
    text = "# Local secrets. Excluded from Git and Docker build context.\n"
    text += "\n".join(f"{k}={v}" for k, v in settings.items()) + "\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def initialize():
    settings = read_settings()
    if not settings.get("LOCAL_DB_PASSWORD"):
        settings["LOCAL_DB_PASSWORD"] = secrets.token_urlsafe(32)
    save_settings(settings)
    return settings


def configure():
    settings = initialize()
    print("Введите ключи. Ввод скрыт; Enter сохраняет прежнее значение.")
    for key, label in [
        ("TELEGRAM_TOKEN", "Токен существующего Telegram-бота"),
        ("OPENROUTER_API_KEY", "Ключ OpenRouter"),
    ]:
        value = getpass.getpass(label + ": ").strip()
        if value:
            if any(c in value for c in "\r\n\"'#$ "):
                raise SystemExit("В ключе недопустимые символы. Вставьте только значение ключа.")
            settings[key] = value
    print("Для того же токена остановите прежний ресурс в Coolify (bot и worker).")
    answer = (
        input("Серверный экземпляр уже остановлен? Введите ДА или оставьте пустым: ")
        .strip()
        .casefold()
    )
    settings["SERVER_INSTANCE_STOPPED"] = "yes" if answer in ("да", "yes") else "no"
    save_settings(settings)
    print("Настройки сохранены локально. Значения ключей не выводятся.")


def compose(args, preview=False):
    settings = read_settings()
    env = dict(os.environ)
    # Prevent ambient shell variables from silently replacing this installation's settings.
    env.update(settings)
    if preview:
        env["TELEGRAM_TOKEN"] = ""
        env["OPENROUTER_API_KEY"] = ""
        env["MINI_APP_URL"] = ""
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(ROOT / "compose.local.yaml"),
        *args,
    ]
    try:
        return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    except FileNotFoundError:
        raise SystemExit(
            "Docker Desktop не найден. Запустите установленный Docker Desktop."
        ) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("init", "configure", "start", "preview", "stop", "status")
    )
    args = parser.parse_args()
    if args.action == "configure":
        configure()
        return
    settings = initialize()
    if args.action == "init":
        print("Локальная конфигурация создана; ключи можно ввести через SETUP_LOCAL.cmd.")
        return
    if args.action == "start":
        if not settings["TELEGRAM_TOKEN"] or not settings["OPENROUTER_API_KEY"]:
            raise SystemExit(
                "Сначала откройте SETUP_LOCAL.cmd и введите ключи. Не отправляйте их в чат."
            )
        if settings["SERVER_INSTANCE_STOPPED"] != "yes":
            raise SystemExit(
                "Прежний серверный экземпляр ещё не отмечен как остановленный. Остановите его и повторите SETUP_LOCAL.cmd; до этого доступен PREVIEW_LOCAL.cmd."
            )
    actions = {
        "start": ["up", "-d", "--build", "--wait", "--wait-timeout", "180"],
        "preview": ["up", "-d", "--build", "--wait", "--wait-timeout", "180"],
        "stop": ["stop"],
        "status": ["ps"],
    }
    code = compose(actions[args.action], preview=args.action == "preview")
    if not code and args.action in ("start", "preview"):
        print("Лента на этом компьютере: http://127.0.0.1:" + settings["LOCAL_FEED_PORT"])
        print("Компьютер и Docker Desktop должны работать для сбора и сводки в 09:00 МСК.")
        if args.action == "preview":
            print("Режим просмотра: Telegram и платный анализ выключены.")
        else:
            print(
                "Отправьте /start существующему боту, затем /status. Подписка сохранится в локальной базе."
            )
    sys.exit(code)


if __name__ == "__main__":
    main()
