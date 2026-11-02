import json
import os
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path

MSK = timezone(timedelta(hours=3), "Москва")
CONFIG = json.loads(
    Path(
        os.environ.get("RADAR_CONFIG", Path(__file__).resolve().parents[1] / "config/radar.json")
    ).read_text(encoding="utf-8")
)
if not Decimal(0) < Decimal(CONFIG["daily_budget_usd"]) <= Decimal("1.00"):
    raise ValueError("Суточный бюджет должен быть больше нуля и не выше $1")
