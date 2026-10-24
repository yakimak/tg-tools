r"""Читает последние сообщения и сохраняет их в JSONL.

Запуск:
    .\.venv\Scripts\python.exe examples\read_and_export.py [@chat]
"""

from __future__ import annotations

import asyncio
import sys

import _bootstrap  # noqa: F401
from tgtools import TelegramAPI


async def main() -> None:
    chat = sys.argv[1] if len(sys.argv) > 1 else "@durov"

    async with TelegramAPI() as tg:
        me = await tg.get_me()
        print(f"Аккаунт: {me['title']} (id={me['id']})")

        chats = await tg.list_chats(limit=5)
        print("Последние чаты:")
        for item in chats:
            print(f"  {item['id']:>15}  {item['title']}")

        messages = await tg.read_messages(chat, limit=20)
        print(f"\n{chat}: {len(messages)} сообщений")
        for message in reversed(messages):
            text = (message["text"] or "").replace("\n", " ")
            print(f"  [{message['date']}] {message['sender_name']}: {text[:100]}")

        result = await tg.export_messages(chat, "exports/demo.jsonl", limit=100)
        print(f"\nСохранено: {result['path']} ({result['count']} сообщений)")


if __name__ == "__main__":
    asyncio.run(main())
