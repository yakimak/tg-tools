"""Асинхронный клиент Telegram API с готовыми функциями.

Работает через официальный API (MTProto, библиотека Telethon), а не через
автоматизацию окна Telegram Desktop. Desktop-приложение нужно только для
получения кода входа.
"""

from __future__ import annotations

import asyncio
import getpass
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable, Sequence

from telethon import TelegramClient, events, types
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    InviteRequestSentError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import (
    GetFullChannelRequest,
    JoinChannelRequest,
    LeaveChannelRequest,
)
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    CreateChatRequest,
    DeleteChatUserRequest,
    GetFullChatRequest,
    ImportChatInviteRequest,
)
from telethon.tl.functions.users import GetFullUserRequest

from .config import Settings
from .errors import (
    AmbiguousChatError,
    ChatNotFoundError,
    InviteRequiredError,
    LoginError,
    MediaNotFoundError,
    NotAuthorizedError,
    TGError,
)
from .models import (
    dialog_to_dict,
    display_name,
    entity_to_dict,
    media_info,
    message_to_dict,
)
from .utils import (
    MEDIA_TYPES,
    human_size,
    parse_telegram_link,
    safe_filename,
    split_media_types,
    unique_path,
)

ProgressCallback = Callable[[str, int, int], None]


class TelegramAPI:
    """Готовый набор функций для личного аккаунта или бота Telegram."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.settings.validate()
        self.settings.ensure_directories()

        self.client = TelegramClient(
            self.settings.session_name,
            self.settings.api_id,
            self.settings.api_hash,
            device_model="TG Tools",
            system_version=platform.platform(terse=True),
            app_version="1.0",
            lang_code="ru",
            system_lang_code="ru",
            connection_retries=3,
            request_retries=3,
            retry_delay=1,
            timeout=20,
            auto_reconnect=True,
            flood_sleep_threshold=self.settings.flood_sleep_threshold,
        )
        self._started = False
        self._me: Any = None
        self._dialogs_cache: list[Any] | None = None

    # ------------------------------------------------------------------
    # Подключение и авторизация
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TelegramAPI":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self, *, interactive: bool = True) -> "TelegramAPI":
        if self._started:
            return self

        try:
            await self.client.connect()
        except AuthKeyUnregisteredError as exc:
            raise NotAuthorizedError(
                f"Сессия недействительна. Удалите {self.settings.session_path} и войдите заново."
            ) from exc

        try:
            try:
                authorized = await self.client.is_user_authorized()
            except AuthKeyUnregisteredError as exc:
                raise NotAuthorizedError(
                    f"Сессия недействительна. Удалите {self.settings.session_path} и войдите заново."
                ) from exc

            if not authorized:
                if not interactive:
                    raise NotAuthorizedError(
                        "Нет авторизованной сессии. Запустите один раз без --no-input: "
                        f"tg login (файл сессии: {self.settings.session_path})."
                    )
                await self._login()

            self._me = await self.client.get_me()
            is_bot = bool(getattr(self._me, "bot", False))
            if self.settings.mode == "bot" and not is_bot:
                raise LoginError(
                    "В файле сессии авторизован обычный пользователь, а TG_MODE=bot. "
                    f"Укажите отдельный TG_SESSION или удалите {self.settings.session_path}."
                )
            if self.settings.mode == "user" and is_bot:
                raise LoginError(
                    "В файле сессии авторизован бот, а TG_MODE=user. "
                    f"Укажите отдельный TG_SESSION или удалите {self.settings.session_path}."
                )
        except Exception:
            await self.close()
            raise

        self._started = True
        return self

    async def _login(self) -> None:
        if self.settings.mode == "bot":
            if not self.settings.bot_token:
                raise LoginError("Для режима bot нужен TG_BOT_TOKEN.")
            try:
                await self.client.sign_in(bot_token=self.settings.bot_token)
            except Exception as exc:
                raise LoginError(f"Не удалось войти как бот: {exc}") from exc
            return

        phone = self.settings.phone
        if not phone:
            print(
                "Введите номер телефона в международном формате, например +79991234567.\n"
                "Код придёт в Telegram (в том числе в Desktop-приложение).",
                file=sys.stderr,
            )
            try:
                phone = input("Телефон: ").strip()
            except EOFError as exc:
                raise NotAuthorizedError("Нет телефона для входа (TG_PHONE не задан).") from exc
        if not phone:
            raise LoginError("Телефон не указан.")

        try:
            sent = await self.client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            raise LoginError(f"Telegram считает номер неверным: {phone}") from exc
        except FloodWaitError as exc:
            raise LoginError(f"Слишком много попыток. Подождите {exc.seconds} секунд.") from exc

        print("Код отправлен. Если Telegram просит подтвердить вход — подтвердите в приложении.", file=sys.stderr)
        for attempt in range(1, 4):
            try:
                code = input(f"Код из Telegram (попытка {attempt}/3): ").strip().replace(" ", "").replace("-", "")
            except EOFError as exc:
                raise NotAuthorizedError("Ввод кода прерван.") from exc
            if not code:
                print("Пустой код, попробуйте снова.", file=sys.stderr)
                continue

            try:
                await self.client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=sent.phone_code_hash,
                )
                return
            except SessionPasswordNeededError:
                await self._login_with_password()
                return
            except PhoneCodeInvalidError:
                print("Неверный код. Проверьте цифры и попробуйте ещё раз.", file=sys.stderr)
            except PhoneCodeExpiredError:
                print("Код истёк, отправляю новый.", file=sys.stderr)
                sent = await self.client.send_code_request(phone)
            except FloodWaitError as exc:
                raise LoginError(f"Слишком много попыток. Подождите {exc.seconds} секунд.") from exc

        raise LoginError("Не удалось ввести код за 3 попытки. Запустите вход заново.")

    async def _login_with_password(self) -> None:
        password = self.settings.password
        if password:
            try:
                await self.client.sign_in(password=password)
                return
            except PasswordHashInvalidError:
                print("Пароль 2FA из TG_PASSWORD не подошёл, введите его вручную.", file=sys.stderr)

        print("Включена двухэтапная аутентификация (2FA).", file=sys.stderr)
        for attempt in range(1, 4):
            try:
                password = getpass.getpass(f"Пароль 2FA (попытка {attempt}/3): ")
            except EOFError as exc:
                raise NotAuthorizedError("Ввод пароля 2FA прерван.") from exc
            try:
                await self.client.sign_in(password=password)
                return
            except PasswordHashInvalidError:
                print("Неверный пароль 2FA.", file=sys.stderr)
        raise LoginError("Не удалось ввести пароль 2FA за 3 попытки.")

    async def close(self) -> None:
        self._started = False
        self._dialogs_cache = None
        try:
            await self.client.disconnect()
        except Exception:
            pass

    @property
    def me(self) -> Any:
        return self._me

    async def get_me(self) -> dict[str, Any]:
        user = await self.client.get_me()
        self._me = user
        return entity_to_dict(user)

    # ------------------------------------------------------------------
    # Чаты и сущности
    # ------------------------------------------------------------------

    async def list_chats(
        self,
        limit: int | None = 50,
        *,
        archived: bool | None = None,
        folder: int | None = None,
    ) -> list[dict[str, Any]]:
        dialogs = []
        async for dialog in self.client.iter_dialogs(
            limit=limit,
            archived=archived,
            folder=folder,
        ):
            dialogs.append(dialog_to_dict(dialog))
        return dialogs

    async def _load_dialogs(self, *, force: bool = False) -> list[Any]:
        if force or self._dialogs_cache is None:
            self._dialogs_cache = list(await self.client.get_dialogs(limit=None))
        return self._dialogs_cache

    def _invalidate_dialogs(self) -> None:
        self._dialogs_cache = None

    @staticmethod
    def _raw_channel_id(marked_id: int) -> int | None:
        text = str(marked_id)
        if text.startswith("-100") and len(text) > 4:
            return int(text[4:])
        return None

    async def resolve(self, ref: Any) -> Any:
        """Принимает @username, ссылку t.me, id, телефон или название чата."""

        if not isinstance(ref, str):
            return ref

        original = ref
        text = ref.strip()
        if not text:
            raise ChatNotFoundError("Пустая ссылка на чат.")

        if text.casefold() in {"me", "self", "я", "себя", "saved", "избранное", "избранные"}:
            return await self.client.get_me()

        parsed = parse_telegram_link(text)
        if parsed:
            if parsed.is_invite:
                raise InviteRequiredError(
                    "Это ссылка-приглашение. Сначала вступите в чат: tg join <ссылка>."
                )
            if not parsed.chat:
                raise ChatNotFoundError(f"Не удалось понять ссылку {original!r}.")
            text = parsed.chat

        # Числовой id: положительный — пользователь, отрицательный — чат/канал.
        if re.fullmatch(r"-?\d+", text):
            number = int(text)
            candidates: set[int] = {number, abs(number)}
            raw_channel = self._raw_channel_id(number)
            if raw_channel is not None:
                candidates.add(raw_channel)

            # Для отрицательных id сначала ищем в диалогах: так не нужен access_hash.
            if number < 0:
                entity = await self._find_entity_in_dialogs(candidates)
                if entity is not None:
                    return entity

            try:
                return await self.client.get_entity(number)
            except (ValueError, TypeError, RPCError):
                pass

            entity = await self._find_entity_in_dialogs(candidates)
            if entity is not None:
                return entity
            raise ChatNotFoundError(
                f"Чат с id {number} не найден. Возможно, вы не состоите в нём "
                "или у сессии нет доступа."
            )

        username = text.lstrip("@")
        if username:
            try:
                return await self.client.get_entity(username)
            except (ValueError, TypeError, RPCError):
                pass

        dialogs = await self._load_dialogs()
        folded = text.casefold()
        username_folded = username.casefold()

        exact = [
            dialog
            for dialog in dialogs
            if str(dialog.name or "").casefold() == folded
            or (getattr(dialog.entity, "username", None) or "").casefold() == username_folded
        ]
        if len(exact) == 1:
            return exact[0].entity
        if len(exact) > 1:
            raise AmbiguousChatError(
                original,
                [f"{d.name} (id={d.id})" for d in exact[:10]],
            )

        partial = [
            dialog
            for dialog in dialogs
            if folded in str(dialog.name or "").casefold()
            or (username_folded and username_folded in (getattr(dialog.entity, "username", None) or "").casefold())
        ]
        if len(partial) == 1:
            return partial[0].entity
        if len(partial) > 1:
            raise AmbiguousChatError(
                original,
                [f"{d.name} (id={d.id})" for d in partial[:10]],
            )

        raise ChatNotFoundError(
            f"Чат {original!r} не найден. Укажите @username, ссылку t.me или точное название."
        )

    async def _find_entity_in_dialogs(self, ids: set[int]) -> Any | None:
        dialogs = await self._load_dialogs()
        for dialog in dialogs:
            entity = dialog.entity
            entity_id = getattr(entity, "id", None)
            if dialog.id in ids or entity_id in ids:
                return entity
            if entity_id is not None and abs(entity_id) in ids:
                return entity
        return None

    async def get_chat_info(self, ref: Any, *, full: bool = True) -> dict[str, Any]:
        parsed = parse_telegram_link(ref) if isinstance(ref, str) else None
        if parsed and parsed.is_invite:
            invite = await self.client(CheckChatInviteRequest(parsed.invite_hash))
            chat = getattr(invite, "chat", None)
            if chat is not None:
                return await self.get_chat_info(chat, full=full)
            info = {
                "type": "invite",
                "invite": True,
                "title": getattr(invite, "title", None),
                "about": getattr(invite, "about", None),
                "participants_count": getattr(invite, "participants_count", None),
                "request_needed": getattr(invite, "request_needed", None),
                "link": ref if isinstance(ref, str) else None,
            }
            return {key: value for key, value in info.items() if value is not None}

        entity = await self.resolve(ref)
        full_info = None

        if full:
            try:
                if isinstance(entity, types.Channel):
                    full_info = (await self.client(GetFullChannelRequest(entity))).full_chat
                elif isinstance(entity, types.User):
                    full_info = (await self.client(GetFullUserRequest(entity))).full_user
                elif isinstance(entity, types.Chat):
                    full_info = (await self.client(GetFullChatRequest(entity.id))).full_chat
            except RPCError:
                full_info = None

        result = entity_to_dict(entity, full=full_info)
        result["input_ref"] = str(ref)
        return result

    async def get_participants(
        self,
        chat: Any,
        *,
        limit: int = 200,
        search: str = "",
    ) -> list[dict[str, Any]]:
        entity = await self.resolve(chat)
        result = []
        async for user in self.client.iter_participants(
            entity,
            limit=limit or None,
            search=search or "",
        ):
            result.append(entity_to_dict(user))
        return result

    # ------------------------------------------------------------------
    # Сообщения
    # ------------------------------------------------------------------

    async def iter_messages(
        self,
        chat: Any,
        *,
        limit: int = 50,
        search: str | None = None,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        from_user: Any = None,
        media_only: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Итерирует сообщения, отдавая словари. ``limit=0`` — без ограничения."""

        entity = await self.resolve(chat)
        limit_value = int(limit) if limit and limit > 0 else None

        if media_only:
            async for message in self._iter_media(
                entity,
                MEDIA_TYPES,
                limit=limit_value,
                since=since,
                until=until,
                reverse=reverse,
                offset_id=offset_id,
                min_id=min_id,
                max_id=max_id,
                search=search,
                from_user=from_user,
            ):
                yield message_to_dict(message)
            return

        source_limit = None if since else limit_value
        from_entity = await self.resolve(from_user) if from_user else None

        async for message in self.client.iter_messages(
            entity,
            limit=source_limit,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id,
            reverse=reverse,
            search=search,
            offset_date=until,
            from_user=from_entity,
        ):
            if not self._date_matches(message, since, until, reverse=reverse):
                if self._should_break(message, since, until, reverse=reverse):
                    break
                continue

            yield message_to_dict(message)

            if limit_value is not None:
                limit_value -= 1
                if limit_value <= 0:
                    break

    async def read_messages(
        self,
        chat: Any,
        *,
        limit: int = 20,
        search: str | None = None,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        reverse: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        from_user: Any = None,
        media_only: bool = False,
    ) -> list[dict[str, Any]]:
        result = []
        async for message in self.iter_messages(
            chat,
            limit=limit,
            search=search,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id,
            reverse=reverse,
            since=since,
            until=until,
            from_user=from_user,
            media_only=media_only,
        ):
            result.append(message)
        return result

    async def search_messages(
        self,
        chat: Any,
        query: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return await self.read_messages(
            chat,
            limit=limit,
            search=query,
            since=since,
            until=until,
        )

    async def get_message(self, chat: Any, message_id: int) -> dict[str, Any] | None:
        entity = await self.resolve(chat)
        message = await self.client.get_messages(entity, ids=message_id)
        if not message or isinstance(message, types.MessageEmpty):
            return None
        return message_to_dict(message, chat=entity)

    async def send_message(
        self,
        chat: Any,
        text: str,
        *,
        reply_to: int | None = None,
        silent: bool = False,
        parse_mode: str | None = "md",
        link_preview: bool = True,
    ) -> dict[str, Any]:
        entity = await self.resolve(chat)
        message = await self.client.send_message(
            entity,
            text,
            reply_to=reply_to,
            silent=silent or None,
            parse_mode=parse_mode,
            link_preview=link_preview,
        )
        sender = None if isinstance(entity, types.Channel) else self._me
        return message_to_dict(message, chat=entity, sender=sender)

    async def edit_message(
        self,
        chat: Any,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "md",
        link_preview: bool = True,
    ) -> dict[str, Any]:
        entity = await self.resolve(chat)
        message = await self.client.edit_message(
            entity,
            message_id,
            text,
            parse_mode=parse_mode,
            link_preview=link_preview,
        )
        sender = None if isinstance(entity, types.Channel) else self._me
        return message_to_dict(message, chat=entity, sender=sender)

    async def send_file(
        self,
        chat: Any,
        files: str | Path | Iterable[str | Path],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        silent: bool = False,
        parse_mode: str | None = "md",
    ) -> list[dict[str, Any]]:
        entity = await self.resolve(chat)
        paths = self._expand_paths(files)
        if not paths:
            raise TGError("Не передано ни одного файла.")

        result: list[dict[str, Any]] = []
        first_batch = True
        for start in range(0, len(paths), 10):
            batch = paths[start : start + 10]
            batch_caption = caption if first_batch else None
            sent = await self.client.send_file(
                entity,
                [str(path) for path in batch] if len(batch) > 1 else str(batch[0]),
                caption=batch_caption,
                reply_to=reply_to,
                silent=silent or None,
                parse_mode=parse_mode,
            )
            first_batch = False
            messages = sent if isinstance(sent, (list, tuple)) else [sent]
            sender = None if isinstance(entity, types.Channel) else self._me
            for message in messages:
                if message is not None:
                    result.append(message_to_dict(message, chat=entity, sender=sender))
        return result

    async def forward_messages(
        self,
        from_chat: Any,
        message_ids: Sequence[int],
        to_chat: Any,
        *,
        silent: bool = False,
    ) -> list[dict[str, Any]]:
        source = await self.resolve(from_chat)
        target = await self.resolve(to_chat)
        sent = await self.client.forward_messages(
            target,
            list(message_ids),
            source,
            silent=silent or None,
        )
        messages = sent if isinstance(sent, (list, tuple)) else [sent]
        return [message_to_dict(message, chat=target) for message in messages if message]

    async def delete_messages(
        self,
        chat: Any,
        message_ids: Sequence[int],
        *,
        revoke: bool = True,
    ) -> dict[str, Any]:
        entity = await self.resolve(chat)
        ids = [int(value) for value in message_ids]
        if not ids:
            raise TGError("Не передано ни одного id сообщения.")
        await self.client.delete_messages(entity, ids, revoke=revoke)
        return {"chat_id": getattr(entity, "id", None), "deleted": ids, "revoke": revoke}

    async def mark_read(self, chat: Any, *, max_id: int | None = None) -> bool:
        entity = await self.resolve(chat)
        return bool(await self.client.send_read_acknowledge(entity, max_id=max_id))

    async def pin_message(self, chat: Any, message_id: int, *, notify: bool = False) -> bool:
        entity = await self.resolve(chat)
        await self.client.pin_message(entity, message_id, notify=notify)
        return True

    async def unpin_message(self, chat: Any, message_id: int | None = None) -> bool:
        entity = await self.resolve(chat)
        await self.client.unpin_message(entity, message_id)
        return True

    # ------------------------------------------------------------------
    # Файлы
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_paths(files: str | Path | Iterable[str | Path]) -> list[Path]:
        if isinstance(files, (str, Path)):
            raw = [files]
        else:
            raw = list(files)

        paths: list[Path] = []
        for item in raw:
            path = Path(item).expanduser().resolve()
            if path.is_dir():
                paths.extend(sorted(child for child in path.iterdir() if child.is_file()))
            else:
                paths.append(path)

        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise TGError("Файл не найден: " + ", ".join(missing))
        return paths

    async def download_media(
        self,
        chat: Any,
        message_id: int,
        dest: str | Path | None = None,
        *,
        skip_existing: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        entity = await self.resolve(chat)
        message = await self.client.get_messages(entity, ids=int(message_id))
        if not message or isinstance(message, types.MessageEmpty):
            raise MediaNotFoundError(f"Сообщение {message_id} не найдено.")
        if not media_info(message):
            raise MediaNotFoundError(f"В сообщении {message_id} нет медиа.")
        return await self._download_message_media(
            message,
            entity=entity,
            dest=dest,
            skip_existing=skip_existing,
            on_progress=on_progress,
        )

    async def download_by_link(
        self,
        link: str,
        dest: str | Path | None = None,
        *,
        skip_existing: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        parsed = parse_telegram_link(link)
        if not parsed:
            raise ValueError(
                "Ожидается ссылка на сообщение вида https://t.me/channel/123 "
                "или https://t.me/c/123456789/123."
            )
        if parsed.is_invite:
            raise InviteRequiredError("По ссылке-приглашению нельзя скачать файл: нужен id сообщения.")
        if not parsed.chat or parsed.message_id is None:
            raise ValueError("В ссылке нет id сообщения.")
        return await self.download_media(
            parsed.chat,
            parsed.message_id,
            dest,
            skip_existing=skip_existing,
            on_progress=on_progress,
        )

    async def download_chat_media(
        self,
        chat: Any,
        *,
        limit: int = 100,
        media_types: Iterable[str] | None = None,
        dest: str | Path | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        skip_existing: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        entity = await self.resolve(chat)
        kinds = split_media_types(media_types)
        limit_value = int(limit) if limit and limit > 0 else None

        if dest:
            directory = Path(dest).expanduser().resolve()
        else:
            directory = self.settings.download_dir / safe_filename(
                display_name(entity),
                fallback=str(getattr(entity, "id", "chat")),
            )
        directory.mkdir(parents=True, exist_ok=True)

        downloaded: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        skipped = 0

        async for message in self._iter_media(
            entity,
            kinds,
            limit=limit_value,
            since=since,
            until=until,
        ):
            try:
                result = await self._download_message_media(
                    message,
                    entity=entity,
                    dest=directory,
                    skip_existing=skip_existing,
                    on_progress=on_progress,
                )
                if result.get("skipped"):
                    skipped += 1
                downloaded.append(result)
            except FloodWaitError:
                raise
            except Exception as exc:
                errors.append({"message_id": getattr(message, "id", None), "error": str(exc)})

        return {
            "chat": display_name(entity),
            "chat_id": getattr(entity, "id", None),
            "directory": str(directory),
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors,
        }

    async def _download_message_media(
        self,
        message: Any,
        *,
        entity: Any,
        dest: str | Path | None = None,
        skip_existing: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        try:
            file = message.file
        except Exception:
            file = None
        if not file:
            raise MediaNotFoundError(f"В сообщении {getattr(message, 'id', '?')} нет файла.")

        extension = getattr(file, "ext", None) or ""
        if getattr(file, "name", None):
            filename = safe_filename(file.name)
        else:
            filename = safe_filename(f"{message.id}{extension}", fallback=f"{message.id}")

        explicit_target = bool(dest is not None and Path(dest).suffix and not Path(dest).is_dir())
        target: Path
        if explicit_target:
            target = Path(dest).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            directory = Path(dest).expanduser().resolve() if dest else self.settings.download_dir
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / filename

        if target.exists():
            try:
                existing_size = target.stat().st_size
            except OSError:
                existing_size = 0
            expected_size = getattr(file, "size", None)
            same_file = existing_size > 0 and (
                expected_size is None or existing_size == expected_size
            )
            if skip_existing and existing_size > 0 and (same_file or explicit_target):
                return {
                    "chat": display_name(entity),
                    "chat_id": getattr(entity, "id", None),
                    "message_id": message.id,
                    "path": str(target),
                    "name": target.name,
                    "size": existing_size,
                    "size_human": human_size(existing_size),
                    "skipped": True,
                }
            if not explicit_target:
                target = unique_path(target.parent, target.name)

        def callback(current: int, total: int) -> None:
            if on_progress:
                on_progress(target.name, current, total)

        returned = await message.download_media(
            file=str(target),
            progress_callback=callback if on_progress else None,
        )
        if not returned:
            raise MediaNotFoundError(f"Telegram не отдал файл сообщения {message.id}.")

        path = Path(returned)
        size = path.stat().st_size if path.exists() else None
        return {
            "chat": display_name(entity),
            "chat_id": getattr(entity, "id", None),
            "message_id": message.id,
            "path": str(path),
            "name": path.name,
            "size": size,
            "size_human": human_size(size),
            "skipped": False,
        }

    # ------------------------------------------------------------------
    # Экспорт и живые события
    # ------------------------------------------------------------------

    async def export_messages(
        self,
        chat: Any,
        out_path: str | Path,
        *,
        limit: int = 0,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        import json

        out = Path(out_path).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with out.open("w", encoding="utf-8") as handle:
            async for message in self.iter_messages(
                chat,
                limit=limit,
                since=since,
                until=until,
            ):
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
                count += 1
        return {"path": str(out), "count": count}

    async def iter_new_messages(
        self,
        chats: Sequence[Any] | None = None,
        *,
        incoming: bool | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Поток новых сообщений (работает, пока клиент подключён)."""

        entities = None
        if chats:
            entities = []
            for chat in chats:
                entities.append(await self.resolve(chat))

        queue: asyncio.Queue[Any] = asyncio.Queue()
        event_filter = events.NewMessage(chats=entities, incoming=incoming)

        async def handler(event: Any) -> None:
            await queue.put(event.message)

        self.client.add_event_handler(handler, event_filter)
        try:
            while True:
                if timeout is not None:
                    message = await asyncio.wait_for(queue.get(), timeout=timeout)
                else:
                    message = await queue.get()
                yield message_to_dict(message)
        finally:
            self.client.remove_event_handler(handler, event_filter)

    # ------------------------------------------------------------------
    # Вступление/выход/создание чатов
    # ------------------------------------------------------------------

    async def join_chat(self, ref: str) -> dict[str, Any]:
        parsed = parse_telegram_link(ref)
        if parsed and parsed.is_invite and parsed.invite_hash:
            try:
                updates = await self.client(ImportChatInviteRequest(parsed.invite_hash))
                chats = list(getattr(updates, "chats", []) or [])
                self._invalidate_dialogs()
                if chats:
                    return {**entity_to_dict(chats[0]), "joined": True}
                return {"joined": True, "invite_hash": parsed.invite_hash}
            except InviteRequestSentError:
                return {
                    "joined": False,
                    "request_sent": True,
                    "invite_hash": parsed.invite_hash,
                }
            except UserAlreadyParticipantError:
                invite = await self.client(CheckChatInviteRequest(parsed.invite_hash))
                chat = getattr(invite, "chat", None)
                if chat is not None:
                    self._invalidate_dialogs()
                    return {**entity_to_dict(chat), "joined": False, "already_member": True}
                return {"joined": False, "already_member": True}

        entity = await self.resolve(ref)
        if isinstance(entity, types.Channel):
            try:
                await self.client(JoinChannelRequest(entity))
                joined = True
            except UserAlreadyParticipantError:
                joined = False
            self._invalidate_dialogs()
            return {**entity_to_dict(entity), "joined": joined}

        raise TGError(
            "Вступить можно в канал/супергруппу по @username или ссылке-приглашению. "
            "Для обычной группы нужна ссылка-приглашение."
        )

    async def leave_chat(self, chat: Any) -> bool:
        entity = await self.resolve(chat)
        if isinstance(entity, types.Channel):
            await self.client(LeaveChannelRequest(entity))
        elif isinstance(entity, types.Chat):
            await self.client(DeleteChatUserRequest(entity.id, "me"))
        else:
            raise TGError("Это не групповой чат и не канал.")
        self._invalidate_dialogs()
        return True

    async def create_group(self, title: str, users: Sequence[Any]) -> dict[str, Any]:
        resolved = [await self.resolve(user) for user in users]
        if not resolved:
            raise TGError("Нужен хотя бы один участник.")
        updates = await self.client(CreateChatRequest(users=resolved, title=title))
        chats = list(getattr(updates, "chats", []) or [])
        self._invalidate_dialogs()
        if not chats:
            raise TGError("Telegram не вернул созданный чат.")
        return {**entity_to_dict(chats[0]), "created": True}

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def _date_matches(
        self,
        message: Any,
        since: datetime | None,
        until: datetime | None,
        *,
        reverse: bool,
    ) -> bool:
        date = getattr(message, "date", None)
        if date is None:
            return True
        date = self._as_utc(date)
        if since and date < self._as_utc(since):
            return False
        if until and date > self._as_utc(until):
            return False
        return True

    def _should_break(
        self,
        message: Any,
        since: datetime | None,
        until: datetime | None,
        *,
        reverse: bool,
    ) -> bool:
        date = getattr(message, "date", None)
        if date is None:
            return False
        date = self._as_utc(date)
        if not reverse and since and date < self._as_utc(since):
            return True
        if reverse and until and date > self._as_utc(until):
            return True
        return False

    async def _iter_media(
        self,
        entity: Any,
        kinds: set[str],
        *,
        limit: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        reverse: bool = False,
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        search: str | None = None,
        from_user: Any = None,
    ) -> AsyncIterator[Any]:
        from_entity = await self.resolve(from_user) if from_user else None
        count = 0

        async for message in self.client.iter_messages(
            entity,
            limit=None,
            filter=self._server_filter(kinds),
            offset_date=until,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id,
            reverse=reverse,
            search=search,
            from_user=from_entity,
        ):
            if not self._date_matches(message, since, until, reverse=reverse):
                if self._should_break(message, since, until, reverse=reverse):
                    break
                continue

            info = media_info(message)
            if not info or info.get("type") not in kinds:
                continue

            yield message
            count += 1
            if limit is not None and count >= limit:
                break

    @staticmethod
    def _server_filter(kinds: set[str]) -> Any:
        if kinds == {"photo"}:
            return types.InputMessagesFilterPhotos
        if kinds == {"video"}:
            return types.InputMessagesFilterVideo
        if kinds == {"photo", "video"}:
            return types.InputMessagesFilterPhotoVideo
        if kinds == {"audio"}:
            return types.InputMessagesFilterMusic
        if kinds == {"voice"}:
            return types.InputMessagesFilterVoice
        if kinds == {"gif"}:
            return types.InputMessagesFilterGif
        if kinds == {"video_note"}:
            return types.InputMessagesFilterRoundVideo
        if kinds == {"document"}:
            return types.InputMessagesFilterDocument
        return types.InputMessagesFilterEmpty
