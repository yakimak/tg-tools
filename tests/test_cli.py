from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from tgtools import cli


def sample_message() -> dict:
    return {
        "id": 7,
        "date": "2026-10-25T10:30:00+00:00",
        "chat_id": 42,
        "chat_title": "Тест",
        "sender_id": 5,
        "sender_name": "Иван",
        "sender_username": "ivan",
        "text": "Привет [не разметка]",
        "out": False,
        "reply_to": None,
        "media": None,
        "link": None,
    }


class FakeAPI:
    def __init__(self):
        self.settings = SimpleNamespace(session_path=Path("data") / "telegram.session")
        self.calls = []

    async def get_me(self):
        return {"id": 1, "title": "Я", "type": "user", "username": "me"}

    async def list_chats(self, **kwargs):
        self.calls.append(("list_chats", kwargs))
        return [
            {
                "id": 42,
                "title": "Тест",
                "type": "supergroup",
                "username": "test",
                "unread": 2,
                "last_message": {"text": "последнее", "media_type": None},
            }
        ]

    async def read_messages(self, *args, **kwargs):
        self.calls.append(("read_messages", kwargs))
        return [sample_message()]

    async def send_message(self, *args, **kwargs):
        self.calls.append(("send_message", kwargs))
        return sample_message()

    async def send_file(self, *args, **kwargs):
        return [sample_message()]

    async def download_by_link(self, *args, **kwargs):
        return {"path": "downloads/a.jpg", "size_human": "1 КБ", "skipped": False}

    async def download_media(self, *args, **kwargs):
        return {"path": "downloads/a.jpg", "size_human": "1 КБ", "skipped": False}

    async def download_chat_media(self, *args, **kwargs):
        return {
            "chat": "Тест",
            "directory": "downloads/Тест",
            "downloaded": [{"name": "a.jpg", "size_human": "1 КБ"}],
            "skipped": 0,
            "errors": [],
        }

    async def get_chat_info(self, *args, **kwargs):
        return {"id": 42, "title": "Тест", "type": "supergroup"}

    async def get_participants(self, *args, **kwargs):
        return [{"id": 5, "title": "Иван", "username": "ivan", "bot": False}]

    async def forward_messages(self, *args, **kwargs):
        return [sample_message()]

    async def delete_messages(self, *args, **kwargs):
        return {"deleted": [7]}

    async def edit_message(self, *args, **kwargs):
        return sample_message()

    async def mark_read(self, *args, **kwargs):
        return True

    async def pin_message(self, *args, **kwargs):
        return True

    async def unpin_message(self, *args, **kwargs):
        return True

    async def join_chat(self, *args, **kwargs):
        return {"id": 42, "title": "Тест", "joined": True}

    async def leave_chat(self, *args, **kwargs):
        return True

    async def create_group(self, *args, **kwargs):
        return {"id": 42, "title": "Тест"}

    async def export_messages(self, *args, **kwargs):
        return {"path": "out.jsonl", "count": 1}

    async def iter_new_messages(self, *args, **kwargs):
        yield sample_message()

    async def search_messages(self, *args, **kwargs):
        return [sample_message()]


class ParserTests(unittest.TestCase):
    def test_flags_before_and_after_command(self):
        parser = cli.build_parser()
        before = parser.parse_args(["--json", "read", "@test", "--limit", "5"])
        after = parser.parse_args(["read", "@test", "--json", "--limit", "5"])
        self.assertTrue(before.json)
        self.assertTrue(after.json)
        self.assertEqual(after.limit, 5)

    def test_global_options_after_command(self):
        parser = cli.build_parser()
        args = parser.parse_args(["chats", "--json", "--no-input", "--download-dir", "tmp"])
        self.assertTrue(args.json)
        self.assertTrue(args.no_input)
        self.assertEqual(args.download_dir, "tmp")

    def test_send_text(self):
        parser = cli.build_parser()
        args = parser.parse_args(["send", "@test", "привет", "мир"])
        self.assertEqual(args.text, ["привет", "мир"])


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.patches = [
            patch("tgtools.cli.console", Console(file=self.stdout, highlight=False)),
            patch("tgtools.cli.err_console", Console(file=self.stderr, highlight=False)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    async def test_chats_table(self):
        args = Namespace(limit=10, archived=False, folder=None, json=False, quiet=True)
        code = await cli.cmd_chats(self.api, args)
        self.assertEqual(code, 0)
        self.assertIn("Тест", self.stdout.getvalue())

    async def test_chats_json(self):
        args = Namespace(limit=10, archived=False, folder=None, json=True, quiet=True)
        await cli.cmd_chats(self.api, args)
        data = json.loads(self.stdout.getvalue())
        self.assertEqual(data[0]["id"], 42)

    async def test_read(self):
        args = Namespace(
            chat="@test",
            limit=20,
            search=None,
            reverse=False,
            since=None,
            until=None,
            from_user=None,
            media_only=False,
            export=None,
            json=False,
            quiet=True,
        )
        await cli.cmd_read(self.api, args)
        self.assertIn("Привет", self.stdout.getvalue())

    async def test_send_plain(self):
        args = Namespace(
            chat="@test",
            text=["привет"],
            reply_to=None,
            silent=False,
            plain=True,
            no_preview=False,
            json=True,
            quiet=True,
        )
        await cli.cmd_send(self.api, args)
        self.assertEqual(json.loads(self.stdout.getvalue())["id"], 7)

    async def test_download_chat(self):
        args = Namespace(
            chat="@test",
            limit=10,
            media_types=["photo"],
            out=None,
            since=None,
            until=None,
            overwrite=False,
            json=False,
            quiet=True,
        )
        await cli.cmd_download_chat(self.api, args)
        self.assertIn("Скачано", self.stdout.getvalue())

    async def test_watch(self):
        args = Namespace(
            chats=["@test"],
            incoming=None,
            outgoing=None,
            timeout=None,
            limit=1,
            json=True,
            quiet=True,
        )
        await cli.cmd_watch(self.api, args)
        self.assertEqual(json.loads(self.stdout.getvalue())["id"], 7)


if __name__ == "__main__":
    unittest.main()
