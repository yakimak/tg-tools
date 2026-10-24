from __future__ import annotations

import unittest
from datetime import datetime, timezone

from telethon.tl import types

from tgtools.models import entity_to_dict, media_info, message_to_dict


def make_document_message() -> types.Message:
    document = types.Document(
        id=10,
        access_hash=20,
        file_reference=b"",
        date=datetime(2026, 10, 25, tzinfo=timezone.utc),
        mime_type="text/plain",
        size=12,
        dc_id=2,
        attributes=[types.DocumentAttributeFilename(file_name="report.txt")],
        thumbs=None,
        video_thumbs=None,
    )
    return types.Message(
        id=7,
        peer_id=types.PeerUser(42),
        date=datetime(2026, 10, 25, 10, 30, tzinfo=timezone.utc),
        message="файл",
        media=types.MessageMediaDocument(document=document),
    )


class MessageTests(unittest.TestCase):
    def test_document_media(self):
        message = make_document_message()
        info = media_info(message)
        self.assertIsNotNone(info)
        self.assertEqual(info["type"], "document")
        self.assertEqual(info["file_name"], "report.txt")
        self.assertEqual(info["size"], 12)
        self.assertEqual(info["mime_type"], "text/plain")

    def test_message_to_dict(self):
        message = make_document_message()
        data = message_to_dict(message)
        self.assertEqual(data["id"], 7)
        self.assertEqual(data["text"], "файл")
        self.assertTrue(data["has_media"])
        self.assertEqual(data["media"]["type"], "document")
        self.assertEqual(data["chat_id"], 42)
        self.assertIn("2026-10-25T10:30:00", data["date"])

    def test_plain_message(self):
        message = types.Message(
            id=8,
            peer_id=types.PeerUser(42),
            date=datetime(2026, 10, 25, tzinfo=timezone.utc),
            message="привет",
        )
        data = message_to_dict(message)
        self.assertIsNone(data["media"])
        self.assertFalse(data["has_media"])


class EntityTests(unittest.TestCase):
    def test_user(self):
        user = types.User(id=5, first_name="Иван", last_name="Петров", username="ivan")
        data = entity_to_dict(user)
        self.assertEqual(data["id"], 5)
        self.assertEqual(data["type"], "user")
        self.assertEqual(data["title"], "Иван Петров")
        self.assertEqual(data["username"], "ivan")

    def test_channel(self):
        channel = types.Channel(
            id=6,
            title="Новости",
            photo=types.ChatPhotoEmpty(),
            date=None,
            megagroup=True,
        )
        data = entity_to_dict(channel)
        self.assertEqual(data["type"], "supergroup")
        self.assertEqual(data["title"], "Новости")


if __name__ == "__main__":
    unittest.main()
