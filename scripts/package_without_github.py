"""Build self-contained deployment inputs from an explicit runtime-file whitelist."""

import base64
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deploy" / "no-github"


def main():
    files = [ROOT / "main.py", ROOT / "requirements.txt"]
    for directory in ("bot", "collector", "worker", "web", "db", "radar_core", "config"):
        files += [
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in (".py", ".sql", ".json")
        ]
    files = sorted(files)
    manifest = {}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            manifest[name] = hashlib.sha256(data).hexdigest()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    packed = gzip.compress(stream.getvalue(), mtime=0)
    checksum = hashlib.sha256(packed).hexdigest()
    encoded = base64.b64encode(packed).decode("ascii")
    dockerfile = f"""# Self-contained Fintech Change Radar: no Git checkout or registry account.
# Runtime snapshot SHA256: {checksum}
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
WORKDIR /app
RUN python -c "import base64,hashlib,io,tarfile; data=base64.b64decode('{encoded}'); assert hashlib.sha256(data).hexdigest()=='{checksum}'; tarfile.open(fileobj=io.BytesIO(data),mode='r:gz').extractall('/app',filter='data')"
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8080
CMD ["python", "main.py"]
"""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    # Preserve service names, database environment references, and the existing volume.
    inline = "    build:\n      context: .\n      dockerfile_inline: |\n"
    inline += "".join("        " + line + "\n" for line in dockerfile.splitlines())
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    if compose.count("    build: .\n") != 2:
        raise RuntimeError("Compose structure changed; review packaging before release")
    compose = compose.replace("    build: .\n", inline)
    (OUTPUT / "compose.yaml").write_text(compose, encoding="utf-8", newline="\n")
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"archive_sha256": checksum, "files": manifest}, indent=2), encoding="utf-8"
    )
    (OUTPUT / "context").mkdir(exist_ok=True)
    (OUTPUT / "context" / ".dockerignore").write_text("*\n", encoding="utf-8")
    print(
        f"Packaged {len(files)} runtime files; Dockerfile {len(dockerfile.encode())} bytes; no secrets or database files included."
    )


if __name__ == "__main__":
    main()
