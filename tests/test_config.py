from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dotenv import dotenv_values

from tgtools.config import Settings, write_env_file
from tgtools.errors import ConfigError


class SettingsTests(unittest.TestCase):
    def test_validate_ok(self):
        settings = Settings(api_id=12345, api_hash="a" * 32)
        settings.validate()
        self.assertEqual(settings.session_path.suffix, ".session")

    def test_missing_api_id(self):
        with self.assertRaises(ConfigError):
            Settings(api_id=None, api_hash="a" * 32).validate()

    def test_bad_api_hash(self):
        with self.assertRaises(ConfigError):
            Settings(api_id=1, api_hash="short").validate()

    def test_bot_requires_token(self):
        with self.assertRaises(ConfigError):
            Settings(api_id=1, api_hash="a" * 32, mode="bot").validate()

    def test_session_name(self):
        settings = Settings(
            api_id=1,
            api_hash="a" * 32,
            session_file=Path("data") / "my.session",
        )
        self.assertEqual(settings.session_name, str(Path("data") / "my"))
        self.assertEqual(settings.session_path.name, "my.session")


class EnvFileTests(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            settings = Settings(
                api_id=12345,
                api_hash="b" * 32,
                phone="+79991234567",
                mode="user",
                session_file=Path(directory) / "data" / "telegram",
                download_dir=Path(directory) / "downloads",
            )
            write_env_file(path, settings)
            values = dotenv_values(path)
            self.assertEqual(values["TG_API_ID"], "12345")
            self.assertEqual(values["TG_API_HASH"], "b" * 32)
            self.assertEqual(values["TG_PHONE"], "+79991234567")
            self.assertEqual(values["TG_MODE"], "user")
            self.assertTrue(values["TG_SESSION"].endswith("telegram"))


if __name__ == "__main__":
    unittest.main()
