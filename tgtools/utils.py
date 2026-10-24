"""Вспомогательные функции: ссылки, даты, имена файлов, форматирование."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import parse_qs, urlsplit

TELEGRAM_HOSTS = {
    "t.me",
    "www.t.me",
    "telegram.me",
    "www.telegram.me",
    "telegram.dog",
    "www.telegram.dog",
}

MEDIA_TYPES = {
    "photo",
    "video",
    "audio",
    "voice",
    "document",
    "gif",
    "sticker",
    "video_note",
}

_ALIASES = {
    "all": MEDIA_TYPES,
    "все": MEDIA_TYPES,
    "photo": {"photo"},
    "photos": {"photo"},
    "фото": {"photo"},
    "video": {"video"},
    "videos": {"video"},
    "видео": {"video"},
    "photo_video": {"photo", "video"},
    "audio": {"audio"},
    "music": {"audio"},
    "аудио": {"audio"},
    "музыка": {"audio"},
    "voice": {"voice"},
    "голос": {"voice"},
    "голосовые": {"voice"},
    "document": {"document"},
    "documents": {"document"},
    "file": {"document"},
    "files": {"document"},
    "документы": {"document"},
    "файлы": {"document"},
    "gif": {"gif"},
    "гиф": {"gif"},
    "sticker": {"sticker"},
    "stickers": {"sticker"},
    "стикеры": {"sticker"},
    "video_note": {"video_note"},
    "кружки": {"video_note"},
}


@dataclass(frozen=True)
class TelegramLink:
    """Разобранная ссылка Telegram."""

    chat: str | None = None
    message_id: int | None = None
    invite_hash: str | None = None

    @property
    def is_invite(self) -> bool:
        return self.invite_hash is not None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_telegram_link(value: str) -> TelegramLink | None:
    """Разбирает t.me/telegram.me/tg:// ссылки.

    Поддерживаются публичные ссылки, приватные ``t.me/c/...``,
    приглашения ``t.me/+...`` и основные ``tg://`` варианты.
    """

    raw = (value or "").strip()
    if not raw:
        return None

    if raw.lower().startswith("tg://"):
        parts = urlsplit(raw)
        action = (parts.netloc or "").lower()
        query = parse_qs(parts.query)

        if action == "resolve":
            domain = (query.get("domain") or [""])[0].strip().lstrip("@")
            if not domain:
                return None
            return TelegramLink(chat=f"@{domain}", message_id=_as_int((query.get("post") or [None])[0]))

        if action == "privatepost":
            channel = _as_int((query.get("channel") or [None])[0])
            if channel is None:
                return None
            return TelegramLink(
                chat=f"-100{channel}",
                message_id=_as_int((query.get("post") or [None])[0]),
            )

        if action == "join":
            invite = (query.get("invite") or [""])[0].strip()
            return TelegramLink(invite_hash=invite or None)

        if action == "user":
            user_id = _as_int((query.get("id") or [None])[0])
            if user_id is None:
                return None
            return TelegramLink(chat=str(user_id))

        if action in {"openmessage", "message"}:
            chat_id = _as_int((query.get("chat_id") or query.get("channel_id") or [None])[0])
            if chat_id is None:
                return None
            return TelegramLink(
                chat=str(chat_id),
                message_id=_as_int((query.get("message_id") or query.get("post") or [None])[0]),
            )

        return None

    normalized = raw
    if normalized.startswith("//"):
        normalized = "https:" + normalized
    elif not re.match(r"^[a-z]+://", normalized, re.I) and normalized.lower().startswith(
        tuple(f"{host}/" for host in TELEGRAM_HOSTS)
    ):
        normalized = "https://" + normalized

    parts = urlsplit(normalized)
    host = (parts.hostname or "").lower()
    if host not in TELEGRAM_HOSTS:
        return None

    path = parts.path.strip("/")
    if not path:
        return None

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None

    first = segments[0]

    # t.me/s/channel/123 — веб-превью канала.
    if first == "s" and len(segments) >= 2:
        segments = segments[1:]
        first = segments[0]

    if first.startswith("+") and len(first) > 1:
        return TelegramLink(invite_hash=first[1:])

    if first == "joinchat":
        if len(segments) < 2:
            return None
        return TelegramLink(invite_hash=segments[1])

    if first == "c":
        if len(segments) < 2:
            return None
        channel_id = _as_int(segments[1])
        if channel_id is None:
            return None
        return TelegramLink(
            chat=f"-100{channel_id}",
            message_id=_as_int(segments[2]) if len(segments) >= 3 else None,
        )

    # Служебные ссылки, которые не являются чатами.
    if first.lower() in {"addstickers", "addemoji", "addtheme", "proxy", "socks", "share", "login", "iv"}:
        return None

    username = first.lstrip("@")
    if not username:
        return None

    return TelegramLink(
        chat=f"@{username}",
        message_id=_as_int(segments[1]) if len(segments) >= 2 else None,
    )


def parse_id_list(values: Sequence[str]) -> list[int]:
    """Превращает ``["1", "2,3"]`` в ``[1, 2, 3]``."""

    result: list[int] = []
    for value in values:
        for chunk in str(value).split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            result.append(int(chunk))
    return result


def parse_date(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Разбирает дату/время или относительный интервал.

    Примеры: ``2026-10-25``, ``25.10.2026``, ``2026-10-25 18:30``,
    ``2h``, ``7d``, ``30m``, ``1w``, ``today``, ``yesterday``, Unix timestamp.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    current = now or datetime.now(timezone.utc).astimezone()
    local_tz = current.tzinfo or datetime.now().astimezone().tzinfo

    lowered = text.casefold()
    if lowered in {"now", "сейчас"}:
        return current.astimezone(timezone.utc)
    if lowered in {"today", "сегодня"}:
        local_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight.astimezone(timezone.utc)
    if lowered in {"yesterday", "вчера"}:
        local_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return local_midnight.astimezone(timezone.utc)

    match = re.fullmatch(r"(\d+)\s*([mhdwмчднв])", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = {
            "m": 60,
            "м": 60,
            "h": 3600,
            "ч": 3600,
            "d": 86400,
            "д": 86400,
            "w": 604800,
            "н": 604800,
            "в": 604800,
        }[unit]
        return (current - timedelta(seconds=amount * seconds)).astimezone(timezone.utc)

    if re.fullmatch(r"\d{9,11}", text):
        # Unix timestamp (секунды).
        return datetime.fromtimestamp(int(text), tz=timezone.utc)

    iso_candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=local_tz)).astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=local_tz).astimezone(timezone.utc)
        except ValueError:
            continue

    raise ValueError(
        f"Не понимаю дату {value!r}. Примеры: 2026-10-25, 25.10.2026, 2h, 7d, today."
    )


def human_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} Б"


def human_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(name: str | None, fallback: str = "file", max_length: int = 120) -> str:
    """Делает имя файла безопасным для Windows/macOS/Linux."""

    if not name:
        name = fallback
    cleaned = "".join(
        "_" if ch in '<>:"/\\|?*' or ord(ch) < 32 or ord(ch) == 127 else ch
        for ch in str(name)
    )
    cleaned = cleaned.strip().rstrip(". ")
    if not cleaned:
        cleaned = fallback

    path = Path(cleaned)
    stem, suffix = path.stem, path.suffix
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"

    max_length = max(16, max_length)
    if len(stem) + len(suffix) > max_length:
        stem = stem[: max_length - len(suffix) - 1]

    result = stem + suffix
    return result or fallback


def unique_path(directory: Path, filename: str) -> Path:
    """Возвращает свободный путь, добавляя `` (1)``, `` (2)`` и т.д."""

    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 10_000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"Не удалось подобрать свободное имя для {filename}")


def split_media_types(values: Iterable[str] | None) -> set[str]:
    """Разбирает ``--type photo,video`` / ``--type фото``."""

    if not values:
        return set(MEDIA_TYPES)

    result: set[str] = set()
    for value in values:
        for chunk in str(value).replace(";", ",").split(","):
            key = chunk.strip().casefold()
            if not key:
                continue
            if key not in _ALIASES:
                valid = ", ".join(sorted(MEDIA_TYPES))
                raise ValueError(f"Неизвестный тип медиа {chunk!r}. Доступно: {valid}, all")
            result.update(_ALIASES[key])
    return result or set(MEDIA_TYPES)


def truncate(text: str | None, length: int = 120) -> str:
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= length else flat[: length - 1] + "…"


def dumps(value, *, pretty: bool = True) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        default=str,
    )
