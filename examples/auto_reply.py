r"""Простой автоответчик по ключевым словам.

Запуск:
    .\.venv\Scripts\python.exe examples\auto_reply.py @my_chat

Скрипт отвечает не чаще одного раза в 60 секунд на чат и только на входящие
сообщения. Это демонстрация; не используйте для спама.
"""

from __future__ import annotations

import asyncio
import sys
import time

import _bootstrap  # noqa: F401
from tgtools import TelegramAPI

KEYWORDS = {
    "помощь": "Привет! Я на связи и отвечу, как только смогу.",
    "цена": "Актуальные цены пришлю в личные сообщения.",
    "привет": "Привет! 👋",
}

COOLDOWN_SECONDS = 60


async def main() -> None:
    if len(sys.argv) < 2:
        print("Укажите чат(ы): python examples/auto_reply.py @my_chat [@another]")
        return

    chats = sys.argv[1:]
    last_reply: dict[int, float] = {}

    async with TelegramAPI() as tg:
        print(f"Слушаю: {', '.join(chats)}. Ctrl+C — выход.")
        async for message in tg.iter_new_messages(chats, incoming=True):
            text = (message.get("text") or "").casefold()
            if not text:
                continue

            for keyword, answer in KEYWORDS.items():
                if keyword not in text:
                    continue

                chat_id = message["chat_id"]
                now = time.monotonic()
                if now - last_reply.get(chat_id, 0) < COOLDOWN_SECONDS:
                    break

                await tg.send_message(chat_id, answer, reply_to=message["id"])
                last_reply[chat_id] = now
                print(f"Ответили в {message.get('chat_title')}: {answer}")
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено.")
