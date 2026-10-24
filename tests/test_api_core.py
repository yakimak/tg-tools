from __future__ import annotations

import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from telethon.tl import types
from telethon.utils import get_peer_id

from tgtools.api import TelegramAPI
from tgtools.errors import AmbiguousChatError, ChatNotFoundError, NotAuthorizedError


class FakeClient:
    def __init__(self, channel, user, messages):
        self.channel = channel
        self.user = user
        self.messages = messages
        self.calls = []

    async def get_entity(self, ref):
        if ref in {"test", "@test", "testchannel"}:
            return self.channel
        if ref in {self.user, self.user.id}:
            return self.user
        raise ValueError(f"unknown entity {ref!r}")

    async def get_me(self):
        return self.user

    async def get_dialogs(self, limit=None):
        return [
            SimpleNamespace(id=-100123, name="Тестовый канал", entity=self.channel),
            SimpleNamespace(id=5, name="Иван", entity=self.user),
        ]

    def iter_messages(self, entity, **kwargs):
        self.calls.append(("iter_messages", kwargs))

        async def generator():
            for message in self.messages:
                yield message

        return generator()

    async def get_messages(self, entity, ids):
        return self.messages[0] if self.messages else None

    async def send_message(self, entity, text, **kwargs):
        self.calls.append(("send_message", text, kwargs))
        return self.messages[0]

    async def edit_message(self, entity, message_id, text, **kwargs):
        self.calls.append(("edit_message", message_id, text))
        return self.messages[0]

    async def delete_messages(self, entity, ids, **kwargs):
        self.calls.append(("delete_messages", ids, kwargs))
        return []

    async def send_read_acknowledge(self, entity, max_id=None):
        self.calls.append(("mark_read", max_id))
        return True

    async def forward_messages(self, entity, ids, from_peer, **kwargs):
        self.calls.append(("forward", ids, from_peer))
        return [self.messages[0]]


def make_entities():
    user = types.User(id=5, first_name="Иван", username="ivan")
    channel = types.Channel(
        id=123,
        title="Тестовый канал",
        username="testchannel",
        photo=types.ChatPhotoEmpty(),
        date=None,
        megagroup=True,
    )
    message = types.Message(
        id=7,
        peer_id=types.PeerChannel(123),
        date=datetime(2026, 10, 25, 10, 30, tzinfo=timezone.utc),
        message="привет",
        from_id=types.PeerUser(5),
    )
    entities = {
        get_peer_id(types.PeerChannel(123)): channel,
        get_peer_id(types.PeerUser(5)): user,
    }
    init_client = SimpleNamespace(_self_id=user.id, _mb_entity_cache=None)
    message._finish_init(init_client, entities, channel)
    return user, channel, message


class APIResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user, self.channel, self.message = make_entities()
        self.client = FakeClient(self.channel, self.user, [self.message])

        self.api = TelegramAPI.__new__(TelegramAPI)
        self.api.client = self.client
        self.api._me = self.user
        self.api._started = True
        self.api._dialogs_cache = None

    async def test_resolve_username(self):
        entity = await self.api.resolve("@test")
        self.assertIs(entity, self.channel)

    async def test_resolve_title(self):
        entity = await self.api.resolve("Тестовый канал")
        self.assertIs(entity, self.channel)

    async def test_resolve_numeric_channel(self):
        entity = await self.api.resolve("-100123")
        self.assertIs(entity, self.channel)

    async def test_resolve_ambiguous(self):
        async def dialogs(limit=None):
            return [
                SimpleNamespace(id=-100123, name="Тест 1", entity=self.channel),
                SimpleNamespace(id=-100124, name="Тест 2", entity=self.channel),
            ]

        self.client.get_dialogs = dialogs
        with self.assertRaises(AmbiguousChatError):
            await self.api.resolve("тест")

    async def test_resolve_missing(self):
        with self.assertRaises(ChatNotFoundError):
            await self.api.resolve("нет такого")


class FakeAuthClient:
    def __init__(self, user):
        self.user = user
        self.authorized = False
        self.sign_in_calls = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return self.authorized

    async def send_code_request(self, phone):
        return SimpleNamespace(phone_code_hash="hash")

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None, bot_token=None):
        self.sign_in_calls.append(
            {"phone": phone, "code": code, "password": password, "bot_token": bot_token}
        )
        self.authorized = True
        return self.user

    async def get_me(self):
        return self.user

    async def disconnect(self):
        self.connected = False


class LoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        user = types.User(id=5, first_name="Иван", username="ivan")
        self.client = FakeAuthClient(user)
        self.api = TelegramAPI.__new__(TelegramAPI)
        self.api.client = self.client
        self.api._started = False
        self.api._me = None
        self.api._dialogs_cache = None
        self.api.settings = SimpleNamespace(
            mode="user",
            phone="+79991234567",
            password=None,
            bot_token=None,
            session_path=Path("data") / "telegram.session",
        )

    async def test_login_with_code(self):
        with patch("builtins.input", return_value="12345"), patch("sys.stderr", new=io.StringIO()):
            await self.api.start(interactive=True)
        self.assertTrue(self.api._started)
        self.assertEqual(self.client.sign_in_calls[0]["code"], "12345")
        self.assertEqual(self.api._me.id, 5)
        await self.api.close()
        self.assertFalse(self.client.connected)

    async def test_no_input_without_session(self):
        with self.assertRaises(NotAuthorizedError):
            await self.api.start(interactive=False)


class APIMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user, self.channel, self.message = make_entities()
        self.client = FakeClient(self.channel, self.user, [self.message])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name

        self.api = TelegramAPI.__new__(TelegramAPI)
        self.api.client = self.client
        self.api._me = self.user
        self.api._started = True
        self.api._dialogs_cache = None
        self.api.settings = SimpleNamespace(download_dir=Path(self.directory))

    async def test_read_messages(self):
        messages = await self.api.read_messages("@test", limit=10)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "привет")
        self.assertEqual(messages[0]["sender_name"], "Иван")
        self.assertEqual(messages[0]["chat_title"], "Тестовый канал")

    async def test_send_message(self):
        result = await self.api.send_message("@test", "новое")
        self.assertEqual(result["id"], 7)
        self.assertEqual(self.client.calls[-1][1], "новое")

    async def test_delete_messages(self):
        result = await self.api.delete_messages("@test", [1, 2])
        self.assertEqual(result["deleted"], [1, 2])
        self.assertEqual(self.client.calls[-1][1], [1, 2])

    async def test_download_media(self):
        class FakeFile:
            name = "photo.jpg"
            size = 3
            mime_type = "image/jpeg"
            ext = ".jpg"

        class DownloadMessage:
            id = 7
            file = FakeFile()
            photo = SimpleNamespace(id=1)

            async def download_media(self, file, progress_callback=None):
                Path(file).write_bytes(b"abc")
                if progress_callback:
                    progress_callback(3, 3)
                return file

        self.client.get_messages = lambda entity, ids: _async_value(DownloadMessage())
        progress = []
        result = await self.api.download_media(
            "@test",
            7,
            dest=Path(self.directory) / "photo.jpg",
            on_progress=lambda name, current, total: progress.append((name, current, total)),
        )
        self.assertEqual(result["name"], "photo.jpg")
        self.assertEqual(result["size"], 3)
        self.assertEqual(progress, [("photo.jpg", 3, 3)])


async def _async_value(value):
    return value


if __name__ == "__main__":
    unittest.main()
