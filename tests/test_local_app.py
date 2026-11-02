import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import local_app


class LocalAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / ".env.local"
        self.env_patch = patch.object(local_app, "ENV_FILE", self.path)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_initialization_preserves_password_and_keys(self):
        first = local_app.initialize()
        self.assertGreaterEqual(len(first["LOCAL_DB_PASSWORD"]), 32)
        first["TELEGRAM_TOKEN"] = "test-private-token"
        local_app.save_settings(first)
        second = local_app.initialize()
        self.assertEqual(first, second)

    def test_preview_erases_paid_and_telegram_credentials(self):
        settings = local_app.initialize()
        settings.update(TELEGRAM_TOKEN="test-private-token", OPENROUTER_API_KEY="test-private-key")
        local_app.save_settings(settings)
        with patch("scripts.local_app.subprocess.run") as run:
            run.return_value.returncode = 0
            local_app.compose(["up", "-d"], preview=True)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["TELEGRAM_TOKEN"], "")
        self.assertEqual(env["OPENROUTER_API_KEY"], "")
        self.assertNotIn("test-private-token", repr(run.call_args.args))

    def test_start_requires_keys(self):
        with (
            patch("sys.argv", ["local_app.py", "start"]),
            patch("scripts.local_app.compose") as compose,
        ):
            with self.assertRaises(SystemExit):
                local_app.main()
            compose.assert_not_called()

    def test_start_requires_server_takeover_state(self):
        settings = local_app.initialize()
        settings.update(TELEGRAM_TOKEN="test-private-token", OPENROUTER_API_KEY="test-private-key")
        local_app.save_settings(settings)
        with (
            patch("sys.argv", ["local_app.py", "start"]),
            patch("scripts.local_app.compose") as compose,
        ):
            with self.assertRaises(SystemExit):
                local_app.main()
            compose.assert_not_called()

    def test_local_settings_override_ambient_credentials(self):
        settings = local_app.initialize()
        settings["TELEGRAM_TOKEN"] = "local-value"
        local_app.save_settings(settings)
        with (
            patch.dict(os.environ, {"TELEGRAM_TOKEN": "ambient-value"}),
            patch("scripts.local_app.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            local_app.compose(["ps"])
        self.assertEqual(run.call_args.kwargs["env"]["TELEGRAM_TOKEN"], "local-value")

    def test_local_bot_resets_previous_server_menu(self):
        from bot.main import setup
        from radar_core.config import CONFIG

        with (
            patch("bot.main.page_url", return_value=""),
            patch("bot.main.api", return_value={"username": CONFIG["bot_username"]}) as api,
        ):
            setup(None)
        self.assertEqual(
            api.call_args.args, ("setChatMenuButton", {"menu_button": {"type": "commands"}})
        )
