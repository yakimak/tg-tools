"""Понятные человеку исключения для tg-инструментов."""

from __future__ import annotations


class TGError(RuntimeError):
    """Базовая ошибка инструмента."""


class ConfigError(TGError):
    """Не настроены или неверно заданы параметры в .env."""


class NotAuthorizedError(TGError):
    """Нет авторизованной сессии Telegram."""


class ChatNotFoundError(TGError):
    """Чат/пользователь/канал не найден."""


class AmbiguousChatError(ChatNotFoundError):
    """По названию найдено несколько чатов."""

    def __init__(self, query: str, candidates: list[str]):
        self.query = query
        self.candidates = candidates
        text = "Найдено несколько чатов: " + ", ".join(candidates)
        super().__init__(text)


class InviteRequiredError(TGError):
    """Ссылка-приглашение: сначала нужно вступить в чат."""


class MediaNotFoundError(TGError):
    """В сообщении нет медиа для скачивания."""


class LoginError(TGError):
    """Не удалось войти в аккаунт."""
