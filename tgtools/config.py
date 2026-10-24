"""Конфигурация из .env и параметров командной строки."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_SESSION = "data/telegram"
DEFAULT_DOWNLOAD_DIR = "downloads"
API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def discover_env_file(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_from_env = os.getenv("TG_ENV_FILE")
    if env_from_env:
        return Path(env_from_env).expanduser().resolve()
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env.resolve()
    return DEFAULT_ENV_FILE


def _resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        # Некорректное значение считаем отсутствующим: validate() объяснит,
        # что нужно исправить, а мастер setup сможет перезаписать .env.
        return None


@dataclass
class Settings:
    api_id: int | None = None
    api_hash: str | None = None
    phone: str | None = None
    password: str | None = None
    mode: str = "user"
    bot_token: str | None = None
    session_file: Path = PROJECT_ROOT / DEFAULT_SESSION
    download_dir: Path = PROJECT_ROOT / DEFAULT_DOWNLOAD_DIR
    env_file: Path = DEFAULT_ENV_FILE
    flood_sleep_threshold: int = 60

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> "Settings":
        env_path = discover_env_file(env_file)
        if env_path.exists():
            load_dotenv(env_path, override=False)

        mode = (_env("TG_MODE", "user") or "user").lower()
        api_id = _parse_int(_env("TG_API_ID"))
        api_hash = _env("TG_API_HASH")
        phone = _env("TG_PHONE")
        password = _env("TG_PASSWORD")
        bot_token = _env("TG_BOT_TOKEN")

        session_value = _env("TG_SESSION", DEFAULT_SESSION) or DEFAULT_SESSION
        download_value = _env("TG_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR) or DEFAULT_DOWNLOAD_DIR

        settings = cls(
            api_id=api_id,
            api_hash=api_hash,
            phone=phone,
            password=password,
            mode=mode,
            bot_token=bot_token,
            session_file=_resolve_path(session_value),
            download_dir=_resolve_path(download_value),
            env_file=env_path,
            flood_sleep_threshold=_parse_int(_env("TG_FLOOD_SLEEP_THRESHOLD")) or 60,
        )

        if overrides:
            normalized: dict[str, Any] = {}
            for key, value in overrides.items():
                if value is None:
                    continue
                if key in {"session_file", "download_dir"}:
                    normalized[key] = _resolve_path(value)
                else:
                    normalized[key] = value
            settings = replace(settings, **normalized)

        return settings

    def validate(self) -> None:
        if not self.api_id:
            raise ConfigError(
                "Не задан или неверен TG_API_ID. Получите api_id/api_hash на https://my.telegram.org "
                "и запустите: tg setup"
            )
        if self.api_id <= 0:
            raise ConfigError("TG_API_ID должен быть положительным числом.")
        if not self.api_hash:
            raise ConfigError(
                "Не задан или неверен TG_API_HASH. Получите его на https://my.telegram.org и запустите: tg setup"
            )
        if not API_HASH_RE.fullmatch(self.api_hash.strip()):
            raise ConfigError("TG_API_HASH должен состоять из 32 шестнадцатеричных символов.")
        if self.mode not in {"user", "bot"}:
            raise ConfigError("TG_MODE должен быть 'user' (личный аккаунт) или 'bot' (бот).")
        if self.mode == "bot" and not self.bot_token:
            raise ConfigError("Для TG_MODE=bot задайте TG_BOT_TOKEN.")
        if self.mode == "user" and self.bot_token and not self.phone:
            # Не ошибка: токен может просто остаться в файле от прошлой настройки.
            pass

    @property
    def session_path(self) -> Path:
        """Путь именно к файлу сессии (Telethon сам добавит .session)."""

        path = self.session_file
        if path.suffix != ".session":
            path = path.with_name(path.name + ".session")
        return path

    @property
    def session_name(self) -> str:
        """Имя без расширения, которое принимает Telethon."""

        name = str(self.session_file)
        if name.endswith(".session"):
            name = name[: -len(".session")]
        return name

    def ensure_directories(self) -> None:
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict[str, Any]:
        """Безопасное описание конфигурации (без секретов)."""

        return {
            "mode": self.mode,
            "api_id": self.api_id,
            "phone": self.phone,
            "bot": bool(self.bot_token),
            "session": str(self.session_path),
            "session_exists": self.session_path.exists(),
            "download_dir": str(self.download_dir),
            "env_file": str(self.env_file),
        }


def _env_quote(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return '""'
    if re.search(r"[\s#\"']", text):
        return json.dumps(text, ensure_ascii=False)
    return text


def write_env_file(path: str | Path, settings: Settings) -> Path:
    """Записывает .env. Существующий файл перезаписывается."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    session_value = settings.session_name
    download_value = str(settings.download_dir)
    try:
        download_value = str(Path(download_value).relative_to(PROJECT_ROOT))
    except ValueError:
        pass
    try:
        session_value = str(Path(session_value).relative_to(PROJECT_ROOT))
    except ValueError:
        pass

    lines = [
        "# Конфигурация TG Tools.",
        "# api_id/api_hash: https://my.telegram.org -> API development tools",
        "# Не публикуйте этот файл и файл сессии .session!",
        "",
        f"TG_API_ID={_env_quote(str(settings.api_id) if settings.api_id else '')}",
        f"TG_API_HASH={_env_quote(settings.api_hash)}",
        f"TG_PHONE={_env_quote(settings.phone)}",
        f"TG_MODE={_env_quote(settings.mode)}",
        f"TG_BOT_TOKEN={_env_quote(settings.bot_token)}",
        f"TG_SESSION={_env_quote(session_value)}",
        f"TG_DOWNLOAD_DIR={_env_quote(download_value)}",
        "",
        "# Пароль 2FA. Оставьте пустым, чтобы вводить его при входе.",
        "# Хранить пароль в открытом виде небезопасно.",
        f"TG_PASSWORD={_env_quote(settings.password)}",
        "",
    ]

    target.write_text("\n".join(lines), encoding="utf-8")
    if os.name != "nt":
        try:
            target.chmod(0o600)
        except OSError:
            pass
    return target
