from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tgtools.utils import (
    parse_date,
    parse_telegram_link,
    safe_filename,
    split_media_types,
    unique_path,
)


class TelegramLinkTests(unittest.TestCase):
    def test_public_post(self):
        link = parse_telegram_link("https://t.me/durov/123")
        self.assertIsNotNone(link)
        self.assertEqual(link.chat, "@durov")
        self.assertEqual(link.message_id, 123)

    def test_public_post_without_scheme(self):
        link = parse_telegram_link("t.me/telegram/42?single")
        self.assertIsNotNone(link)
        self.assertEqual(link.chat, "@telegram")
        self.assertEqual(link.message_id, 42)

    def test_private_post(self):
        link = parse_telegram_link("https://t.me/c/123456789/77")
        self.assertIsNotNone(link)
        self.assertEqual(link.chat, "-100123456789")
        self.assertEqual(link.message_id, 77)

    def test_preview_link(self):
        link = parse_telegram_link("https://t.me/s/durov/5")
        self.assertIsNotNone(link)
        self.assertEqual(link.chat, "@durov")
        self.assertEqual(link.message_id, 5)

    def test_invite_links(self):
        plus = parse_telegram_link("https://t.me/+AbCdEf_123")
        joinchat = parse_telegram_link("https://telegram.me/joinchat/AbCdEf")
        self.assertEqual(plus.invite_hash, "AbCdEf_123")
        self.assertEqual(joinchat.invite_hash, "AbCdEf")

    def test_tg_scheme(self):
        resolve = parse_telegram_link("tg://resolve?domain=durov&post=9")
        private = parse_telegram_link("tg://privatepost?channel=555&post=3")
        self.assertEqual(resolve.chat, "@durov")
        self.assertEqual(resolve.message_id, 9)
        self.assertEqual(private.chat, "-100555")
        self.assertEqual(private.message_id, 3)

    def test_non_chat_links(self):
        self.assertIsNone(parse_telegram_link("https://t.me/addstickers/pack"))
        self.assertIsNone(parse_telegram_link("https://example.com/durov/1"))
        self.assertIsNone(parse_telegram_link("@durov"))


class DateTests(unittest.TestCase):
    def test_relative(self):
        now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_date("2h", now=now), now - timedelta(hours=2))
        self.assertEqual(parse_date("7d", now=now), now - timedelta(days=7))
        self.assertEqual(parse_date("30m", now=now), now - timedelta(minutes=30))

    def test_iso(self):
        value = parse_date("2026-10-25T10:30:00Z")
        self.assertEqual(value, datetime(2026, 10, 25, 10, 30, tzinfo=timezone.utc))

    def test_date_only_is_aware(self):
        value = parse_date("25.10.2026")
        self.assertIsNotNone(value)
        self.assertIsNotNone(value.tzinfo)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_date("не дата")


class FilenameTests(unittest.TestCase):
    def test_invalid_chars(self):
        self.assertEqual(safe_filename('a<b>c:"d/e\\f|g?h*i.txt'), "a_b_c__d_e_f_g_h_i.txt")

    def test_reserved(self):
        self.assertEqual(safe_filename("CON.txt"), "_CON.txt")

    def test_empty(self):
        self.assertEqual(safe_filename("   "), "file")

    def test_long_name_keeps_extension(self):
        name = safe_filename("x" * 300 + ".jpg")
        self.assertLessEqual(len(name), 120)
        self.assertTrue(name.endswith(".jpg"))

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "file.txt"
            base.write_text("x", encoding="utf-8")
            self.assertEqual(unique_path(Path(directory), "file.txt").name, "file (1).txt")


class MediaTypesTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(split_media_types(["фото,video"]), {"photo", "video"})
        self.assertEqual(split_media_types(["all"]), split_media_types(None))

    def test_unknown(self):
        with self.assertRaises(ValueError):
            split_media_types(["exe"])


if __name__ == "__main__":
    unittest.main()
