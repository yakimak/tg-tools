"""TG Tools — готовые функции для работы с Telegram через официальный API."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

from .api import TelegramAPI
from .config import PROJECT_ROOT, Settings
from .errors import (
    AmbiguousChatError,
    ChatNotFoundError,
    ConfigError,
    InviteRequiredError,
    LoginError,
    MediaNotFoundError,
    NotAuthorizedError,
    TGError,
)

__version__ = "1.0.0"

T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Короткий помощник для синхронных скриптов: ``run(main())``."""

    return asyncio.run(coro)


__all__ = [
    "AmbiguousChatError",
    "ChatNotFoundError",
    "ConfigError",
    "InviteRequiredError",
    "LoginError",
    "MediaNotFoundError",
    "NotAuthorizedError",
    "PROJECT_ROOT",
    "Settings",
    "TGError",
    "TelegramAPI",
    "run",
    "__version__",
]
