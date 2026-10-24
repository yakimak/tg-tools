r"""Скачивает медиа из чата в папку downloads/<название чата>.

Запуск:
    .\.venv\Scripts\python.exe examples\download_media.py @channel
    .\.venv\Scripts\python.exe examples\download_media.py @channel photo,video
"""

from __future__ import annotations

import asyncio
import sys

import _bootstrap  # noqa: F401
from tgtools import TelegramAPI


def progress(name: str, current: int, total: int) -> None:
    if total:
        percent = current * 100 / total
        print(f"\r{name}: {percent:5.1f}%", end="", flush=True)


async def main() -> None:
    if len(sys.argv) < 2:
        print("Укажите чат: python examples/download_media.py @channel [photo,video]")
        return

    chat = sys.argv[1]
    types = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    async with TelegramAPI() as tg:
        result = await tg.download_chat_media(
            chat,
            limit=100,
            media_types=types,
            skip_existing=True,
            on_progress=progress,
        )
        print()
        print(f"Папка: {result['directory']}")
        print(f"Скачано: {len(result['downloaded'])}, пропущено: {result['skipped']}")
        for error in result["errors"]:
            print(f"  ошибка в сообщении {error['message_id']}: {error['error']}")


if __name__ == "__main__":
    asyncio.run(main())
