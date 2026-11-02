"""Create a pg_dump custom-format backup without logging credentials. Requires pg_dump."""

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def main():
    exe = shutil.which("pg_dump")
    if not exe:
        raise SystemExit(
            "Установите pg_dump версии не ниже версии сервера или используйте резервное копирование в Coolify."
        )
    url = urlsplit(os.environ["DATABASE_URL"])
    env = dict(
        os.environ,
        PGHOST=url.hostname or "",
        PGPORT=str(url.port or 5432),
        PGUSER=unquote(url.username or ""),
        PGPASSWORD=unquote(url.password or ""),
        PGDATABASE=unquote(url.path.lstrip("/")),
    )
    ssl = parse_qs(url.query).get("sslmode")
    if ssl:
        env["PGSSLMODE"] = ssl[0]
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "backups")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("radar-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
    # Exclusive creation prevents overwriting an earlier backup.
    with path.open("xb") as stream:
        result = subprocess.run(
            [exe, "--format=custom", "--no-owner", "--no-acl"],
            env=env,
            stdout=stream,
            stderr=subprocess.PIPE,
        )
    if result.returncode or path.stat().st_size < 100:
        raise SystemExit(
            "Резервная копия не подтверждена; не обновляйте приложение. Проверьте доступ и версию pg_dump. Файл: "
            + str(path)
        )
    print("Резервная копия: " + str(path))


if __name__ == "__main__":
    main()
