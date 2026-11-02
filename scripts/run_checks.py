"""Runs only against the disposable compose.test.yml database."""

import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ["RADAR_TEST_DATABASE_URL"] = (
    "postgresql://radar_test:radar_local_test_only@127.0.0.1:55432/radar_test"
)
suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
out = root / "reports/tests.txt"
out.parent.mkdir(exist_ok=True)
with out.open("w", encoding="utf-8") as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
print(out.read_text(encoding="utf-8"))
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
