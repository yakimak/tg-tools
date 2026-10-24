"""Командная строка TG Tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from telethon.errors import FloodWaitError, RPCError

from . import __version__
from .api import TelegramAPI
from .config import PROJECT_ROOT, Settings, write_env_file
from .errors import ConfigError, TGError
from .utils import (
    dumps,
    human_duration,
    human_size,
    parse_date,
    parse_id_list,
    split_media_types,
    truncate,
)

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

_MEDIA_LABELS = {
    "photo": "фото",
    "video": "видео",
    "audio": "аудио",
    "voice": "голосовое",
    "document": "файл",
    "gif": "GIF",
    "sticker": "стикер",
    "video_note": "кружок",
    "poll": "опрос",
    "location": "геолокация",
    "contact": "контакт",
    "webpage": "ссылка",
    "service": "сервисное",
}

_CHAT_TYPE_LABELS = {
    "user": "личный",
    "bot": "бот",
    "group": "группа",
    "supergroup": "супергруппа",
    "channel": "канал",
    "invite": "приглашение",
    "unknown": "?",
}


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _json_out(value: Any) -> None:
    console.print(dumps(value, pretty=True), markup=False, highlight=False)


def _fmt_date(value: str | None) -> str:
    if not value:
        return "?"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def _fmt_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _print_kv(data: dict[str, Any], title: str | None = None) -> None:
    labels = {
        "id": "ID",
        "entity_id": "ID сущности",
        "title": "Название",
        "type": "Тип",
        "username": "Username",
        "phone": "Телефон",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "bot": "Бот",
        "verified": "Верифицирован",
        "premium": "Premium",
        "deleted": "Удалён",
        "restricted": "Ограничен",
        "scam": "Скам",
        "fake": "Фейк",
        "participants_count": "Участников",
        "online_count": "Онлайн",
        "common_chats_count": "Общих чатов",
        "about": "О себе",
        "megagroup": "Супергруппа",
        "broadcast": "Канал",
        "linked_chat_id": "Связанный чат",
        "pinned_msg_id": "Закреплённое сообщение",
        "request_needed": "Нужна заявка",
        "invite": "Приглашение",
        "link": "Ссылка",
        "input_ref": "Запрос",
        "status": "Статус",
    }
    table = Table(title=title, show_header=False, box=box.SIMPLE, pad_edge=False)
    table.add_column("Поле", style="cyan", no_wrap=True)
    table.add_column("Значение", overflow="fold")
    for key, value in data.items():
        if value is None or value == "" or value is False:
            continue
        table.add_row(labels.get(key, key), escape(_fmt_value(value)))
    console.print(table)


def _print_message(message: dict[str, Any]) -> None:
    sender = (
        message.get("sender_name")
        or message.get("chat_title")
        or message.get("sender_username")
        or message.get("sender_id")
        or "?"
    )
    direction = "→ " if message.get("out") else ""
    header = f"[dim]{_fmt_date(message.get('date'))}[/dim] [bold cyan]{escape(str(sender))}[/bold cyan]"
    username = message.get("sender_username")
    if username:
        header += f" [dim]@{escape(str(username))}[/dim]"
    header += f" [dim]#{message.get('id')}[/dim]"
    if message.get("reply_to"):
        header += f" [dim]↪{message.get('reply_to')}[/dim]"
    console.print(direction + header)

    text = message.get("text") or ""
    if text:
        console.print(escape(text), markup=True, soft_wrap=True)

    media = message.get("media")
    if media:
        parts = [_MEDIA_LABELS.get(media.get("type"), media.get("type") or "медиа")]
        if media.get("file_name"):
            parts.append(str(media["file_name"]))
        if media.get("size") is not None:
            parts.append(human_size(media["size"]))
        if media.get("duration") is not None:
            parts.append(human_duration(media["duration"]))
        if media.get("url"):
            parts.append(str(media["url"]))
        console.print("[magenta]📎 " + escape(" · ".join(parts)) + "[/magenta]")

    if message.get("link"):
        console.print(f"[dim]{escape(str(message['link']))}[/dim]")
    console.print()


def _print_messages(messages: list[dict[str, Any]]) -> None:
    if not messages:
        console.print("[yellow]Сообщений не найдено.[/yellow]")
        return
    for message in messages:
        _print_message(message)


def _write_jsonl(path: Path, messages: list[dict[str, Any]]) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for message in messages:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")
    return path


def _make_progress(quiet: bool) -> tuple[Progress | None, Callable[[str, int, int], None] | None]:
    if quiet or not sys.stderr.isatty():
        return None, None

    progress = Progress(
        TextColumn("[cyan]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=err_console,
        transient=True,
    )
    tasks: dict[str, int] = {}

    def callback(name: str, current: int, total: int) -> None:
        task = tasks.get(name)
        if task is None:
            task = progress.add_task(truncate(name, 45), total=total or None)
            tasks[name] = task
        progress.update(task, completed=current, total=total or None)

    return progress, callback


async def _with_progress(
    quiet: bool,
    factory: Callable[[Callable[[str, int, int], None] | None], Awaitable[Any]],
) -> Any:
    progress, callback = _make_progress(quiet)
    if progress is not None:
        with progress:
            return await factory(callback)
    return await factory(None)


def _parse_dates(args: argparse.Namespace) -> tuple[Any, Any]:
    since_raw = getattr(args, "since", None)
    until_raw = getattr(args, "until", None)
    since = parse_date(since_raw)
    until = parse_date(until_raw)

    # Для --until=2026-10-25 пользователь обычно имеет в виду весь день.
    if until is not None and until_raw:
        text = str(until_raw).strip().casefold()
        date_only = bool(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
            or re.fullmatch(r"\d{2}[./]\d{2}[./]\d{4}", text)
        )
        if date_only or text in {"today", "сегодня", "yesterday", "вчера"}:
            until += timedelta(days=1, microseconds=-1)

    return since, until


# ----------------------------------------------------------------------
# Обработчики команд
# ----------------------------------------------------------------------


async def cmd_me(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.get_me()
    if args.json:
        _json_out(data)
    else:
        _print_kv(data, "Мой аккаунт")
        console.print(f"[dim]Сессия: {escape(str(api.settings.session_path))}[/dim]")
    return 0


async def cmd_login(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.get_me()
    if args.json:
        _json_out(data)
        return 0
    title = data.get("title") or data.get("username") or data.get("id")
    console.print(f"[green]✅ Вход выполнен:[/green] {escape(str(title))}")
    if data.get("username"):
        console.print(f"   @{escape(str(data['username']))}")
    console.print(f"   id: {data.get('id')}")
    console.print(f"   сессия: {escape(str(api.settings.session_path))}")
    return 0


async def cmd_chats(api: TelegramAPI, args: argparse.Namespace) -> int:
    chats = await api.list_chats(
        limit=args.limit or None,
        archived=bool(args.archived),
        folder=args.folder,
    )
    if args.json:
        _json_out(chats)
        return 0
    if not chats:
        console.print("[yellow]Чатов не найдено.[/yellow]")
        return 0

    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Название", overflow="fold")
    table.add_column("Тип", no_wrap=True)
    table.add_column("Username", no_wrap=True)
    table.add_column("Не проч.", justify="right", no_wrap=True)
    table.add_column("Последнее", overflow="fold")

    for chat in chats:
        last = chat.get("last_message") or {}
        last_text = last.get("text") or ""
        last_desc = truncate(last_text, 50) if last_text else ""
        if last.get("media_type"):
            last_desc = f"[{_MEDIA_LABELS.get(last['media_type'], last['media_type'])}] {last_desc}".strip()
        table.add_row(
            str(chat.get("id")),
            escape(str(chat.get("title") or "")),
            _CHAT_TYPE_LABELS.get(chat.get("type"), chat.get("type") or "?"),
            f"@{chat['username']}" if chat.get("username") else "",
            f"[red]{chat.get('unread', 0)}[/red]" if chat.get("unread") else "",
            escape(last_desc),
        )
    console.print(table)
    return 0


async def cmd_read(api: TelegramAPI, args: argparse.Namespace) -> int:
    since, until = _parse_dates(args)
    messages = await api.read_messages(
        args.chat,
        limit=args.limit,
        search=args.search or None,
        reverse=args.reverse,
        since=since,
        until=until,
        from_user=args.from_user,
        media_only=args.media_only,
    )

    if args.export:
        path = _write_jsonl(Path(args.export), messages)
        if args.json:
            err_console.print(f"[dim]Экспортировано в {escape(str(path))}[/dim]")
        else:
            console.print(f"[green]Экспортировано:[/green] {escape(str(path))} ({len(messages)} сообщ.)")

    if args.json:
        _json_out(messages)
    else:
        _print_messages(messages)
    return 0


async def cmd_send(api: TelegramAPI, args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        raise TGError("Пустой текст. Пример: tg send @username \"Привет!\"")

    message = await api.send_message(
        args.chat,
        text,
        reply_to=args.reply_to,
        silent=args.silent,
        parse_mode=None if args.plain else "md",
        link_preview=not args.no_preview,
    )
    if args.json:
        _json_out(message)
        return 0

    console.print(f"[green]✅ Отправлено[/green] (id={message.get('id')})")
    if message.get("link"):
        console.print(f"[dim]{escape(str(message['link']))}[/dim]")
    return 0


async def cmd_send_file(api: TelegramAPI, args: argparse.Namespace) -> int:
    messages = await api.send_file(
        args.chat,
        args.files,
        caption=args.caption,
        reply_to=args.reply_to,
        silent=args.silent,
        parse_mode=None if args.plain else "md",
    )
    if args.json:
        _json_out(messages)
        return 0
    console.print(f"[green]✅ Отправлено файлов: {len(messages)}[/green]")
    for message in messages:
        console.print(f"   id={message.get('id')} {escape(str((message.get('media') or {}).get('file_name') or ''))}")
    return 0


async def cmd_download(api: TelegramAPI, args: argparse.Namespace) -> int:
    result = await _with_progress(
        args.quiet,
        lambda callback: api.download_by_link(
            args.link,
            args.out,
            skip_existing=not args.overwrite,
            on_progress=callback,
        ),
    )
    if args.json:
        _json_out(result)
        return 0
    if result.get("skipped"):
        console.print(f"[yellow]Уже существует:[/yellow] {escape(str(result['path']))}")
    else:
        console.print(f"[green]✅ Скачано:[/green] {escape(str(result['path']))} ({result.get('size_human')})")
    return 0


async def cmd_download_message(api: TelegramAPI, args: argparse.Namespace) -> int:
    result = await _with_progress(
        args.quiet,
        lambda callback: api.download_media(
            args.chat,
            args.message_id,
            args.out,
            skip_existing=not args.overwrite,
            on_progress=callback,
        ),
    )
    if args.json:
        _json_out(result)
        return 0
    if result.get("skipped"):
        console.print(f"[yellow]Уже существует:[/yellow] {escape(str(result['path']))}")
    else:
        console.print(f"[green]✅ Скачано:[/green] {escape(str(result['path']))} ({result.get('size_human')})")
    return 0


async def cmd_download_chat(api: TelegramAPI, args: argparse.Namespace) -> int:
    since, until = _parse_dates(args)
    media_types = split_media_types(args.media_types) if args.media_types else None
    result = await _with_progress(
        args.quiet,
        lambda callback: api.download_chat_media(
            args.chat,
            limit=args.limit,
            media_types=media_types,
            dest=args.out,
            since=since,
            until=until,
            skip_existing=not args.overwrite,
            on_progress=callback,
        ),
    )
    if args.json:
        _json_out(result)
        return 0

    downloaded = result.get("downloaded", [])
    errors = result.get("errors", [])
    actual = sum(1 for item in downloaded if not item.get("skipped"))
    console.print(f"[bold]Чат:[/bold] {escape(str(result.get('chat')))}")
    console.print(f"[bold]Папка:[/bold] {escape(str(result.get('directory')))}")
    console.print(
        f"[green]Скачано: {actual}[/green]"
        f" · пропущено: {result.get('skipped', 0)}"
        f" · ошибок: {len(errors)}"
    )
    for item in downloaded[:50]:
        prefix = "↷" if item.get("skipped") else "✅"
        console.print(
            f"  {prefix} {escape(str(item.get('name')))}"
            f" [dim]{item.get('size_human')}[/dim]"
        )
    if len(downloaded) > 50:
        console.print(f"  [dim]… и ещё {len(downloaded) - 50} файлов (см. --json)[/dim]")
    for error in errors:
        console.print(
            f"  [red]✖[/red] id={error.get('message_id')}: {escape(str(error.get('error')))}"
        )
    return 0


async def cmd_search(api: TelegramAPI, args: argparse.Namespace) -> int:
    since, until = _parse_dates(args)
    messages = await api.search_messages(
        args.chat,
        args.query,
        limit=args.limit,
        since=since,
        until=until,
    )
    if args.json:
        _json_out(messages)
    else:
        _print_messages(messages)
    return 0


async def cmd_info(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.get_chat_info(args.chat, full=True)
    if args.json:
        _json_out(data)
    else:
        _print_kv(data, "Информация: " + escape(str(data.get("title") or args.chat)))
    return 0


async def cmd_participants(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.get_participants(args.chat, limit=args.limit, search=args.search or "")
    if args.json:
        _json_out(data)
        return 0
    if not data:
        console.print("[yellow]Участники не найдены.[/yellow]")
        return 0

    table = Table(box=box.SIMPLE_HEAD, header_style="bold")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Имя", overflow="fold")
    table.add_column("Username", no_wrap=True)
    table.add_column("Телефон", no_wrap=True)
    table.add_column("Бот")
    for user in data:
        table.add_row(
            str(user.get("id")),
            escape(str(user.get("title") or "")),
            f"@{user['username']}" if user.get("username") else "",
            escape(str(user.get("phone") or "")),
            "да" if user.get("bot") else "",
        )
    console.print(table)
    return 0


async def cmd_forward(api: TelegramAPI, args: argparse.Namespace) -> int:
    ids = parse_id_list(args.ids)
    sent = await api.forward_messages(
        args.from_chat,
        ids,
        args.to_chat,
        silent=args.silent,
    )
    if args.json:
        _json_out(sent)
        return 0
    console.print(f"[green]✅ Переслано сообщений: {len(sent)}[/green]")
    return 0


async def cmd_delete(api: TelegramAPI, args: argparse.Namespace) -> int:
    ids = parse_id_list(args.ids)
    if args.dry_run:
        found = []
        for message_id in ids:
            message = await api.get_message(args.chat, message_id)
            if message:
                found.append(message)
        if args.json:
            _json_out(found)
        else:
            _print_messages(found)
            console.print("[yellow]Режим проверки: ничего не удалено.[/yellow]")
        return 0

    result = await api.delete_messages(args.chat, ids, revoke=not args.keep_for_me)
    if args.json:
        _json_out(result)
    else:
        console.print(f"[green]✅ Удалено сообщений: {len(ids)}[/green]")
    return 0


async def cmd_edit(api: TelegramAPI, args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        raise TGError("Пустой текст для редактирования.")
    message = await api.edit_message(
        args.chat,
        args.message_id,
        text,
        parse_mode=None if args.plain else "md",
    )
    if args.json:
        _json_out(message)
    else:
        console.print(f"[green]✅ Сообщение {args.message_id} изменено.[/green]")
    return 0


async def cmd_mark_read(api: TelegramAPI, args: argparse.Namespace) -> int:
    await api.mark_read(args.chat, max_id=args.max_id)
    if args.json:
        _json_out({"ok": True, "chat": args.chat, "max_id": args.max_id})
    else:
        console.print("[green]✅ Отмечено прочитанным.[/green]")
    return 0


async def cmd_pin(api: TelegramAPI, args: argparse.Namespace) -> int:
    await api.pin_message(args.chat, args.message_id, notify=args.notify)
    if args.json:
        _json_out({"ok": True, "chat": args.chat, "message_id": args.message_id})
    else:
        console.print("[green]✅ Закреплено.[/green]")
    return 0


async def cmd_unpin(api: TelegramAPI, args: argparse.Namespace) -> int:
    await api.unpin_message(args.chat, args.message_id)
    if args.json:
        _json_out({"ok": True, "chat": args.chat, "message_id": args.message_id})
    else:
        console.print("[green]✅ Откреплено.[/green]")
    return 0


async def cmd_join(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.join_chat(args.link)
    if args.json:
        _json_out(data)
    else:
        if data.get("request_sent"):
            status = "заявка на вступление отправлена"
        elif data.get("already_member"):
            status = "уже участник"
        else:
            status = "вход выполнен"
        console.print(f"[green]✅ {status}:[/green] {escape(str(data.get('title') or args.link))}")
    return 0


async def cmd_leave(api: TelegramAPI, args: argparse.Namespace) -> int:
    await api.leave_chat(args.chat)
    if args.json:
        _json_out({"ok": True, "chat": args.chat})
    else:
        console.print("[green]✅ Вы вышли из чата.[/green]")
    return 0


async def cmd_create_group(api: TelegramAPI, args: argparse.Namespace) -> int:
    data = await api.create_group(args.title, args.users)
    if args.json:
        _json_out(data)
    else:
        console.print(f"[green]✅ Группа создана:[/green] {escape(str(data.get('title')))} (id={data.get('id')})")
    return 0


async def cmd_export(api: TelegramAPI, args: argparse.Namespace) -> int:
    since, until = _parse_dates(args)
    out = args.out
    if not out:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(PROJECT_ROOT / "exports" / f"messages_{stamp}.jsonl")
    result = await api.export_messages(
        args.chat,
        out,
        limit=args.limit,
        since=since,
        until=until,
    )
    if args.json:
        _json_out(result)
    else:
        console.print(f"[green]✅ Экспортировано:[/green] {escape(result['path'])} ({result['count']} сообщ.)")
    return 0


async def cmd_watch(api: TelegramAPI, args: argparse.Namespace) -> int:
    incoming = True if args.incoming else False if args.outgoing else None
    count = 0
    try:
        async for message in api.iter_new_messages(
            args.chats or None,
            incoming=incoming,
            timeout=args.timeout,
        ):
            if args.json:
                console.print(dumps(message, pretty=False), markup=False, highlight=False)
            else:
                _print_message(message)
            count += 1
            if args.limit and count >= args.limit:
                break
    except asyncio.TimeoutError:
        if not args.quiet:
            console.print("[dim]Таймаут ожидания новых сообщений.[/dim]")
    return 0


# ----------------------------------------------------------------------
# Настройка и запуск
# ----------------------------------------------------------------------


def _ask(prompt: str, default: str | None = None, *, secret: bool = False) -> str:
    shown = ("[сохранён]" if secret else default) if default else None
    suffix = f" [{shown}]" if shown else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value == "-":
        return ""
    return value or (default or "")


def _resolve_local_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def run_setup(
    env_file: str | Path | None = None,
    *,
    force: bool = False,
    login: bool = False,
    auto: bool = False,
) -> Settings:
    if not sys.stdin.isatty():
        raise ConfigError("Настройка требует интерактивного терминала. Запустите tg setup вручную.")

    existing = Settings.from_env(env_file)
    target = existing.env_file
    if target.exists() and not force:
        answer = input(f"Файл {target} уже существует. Перезаписать? [y/N]: ").strip().casefold()
        if answer not in {"y", "yes", "д", "да"}:
            console.print("[yellow]Оставляю текущую конфигурацию.[/yellow]")
            if login:
                _login_only(existing)
            return existing

    console.print("[bold]Настройка TG Tools[/bold]")
    console.print(
        "Нужны api_id и api_hash. Получите их на [link=https://my.telegram.org]my.telegram.org[/link] "
        "→ API development tools.\n"
        "Это официальный API Telegram, Desktop-приложение не нужно автоматизировать."
    )
    console.print()

    api_id: int | None = existing.api_id
    while True:
        raw = _ask("TG_API_ID", str(existing.api_id) if existing.api_id else None)
        try:
            api_id = int(raw)
            if api_id <= 0:
                raise ValueError
            break
        except ValueError:
            console.print("[red]api_id должен быть числом больше нуля.[/red]")

    while True:
        api_hash = _ask("TG_API_HASH", existing.api_hash, secret=True)
        if re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            break
        console.print("[red]api_hash должен состоять из 32 шестнадцатеричных символов.[/red]")

    mode = _ask("Режим (user — личный аккаунт, bot — бот)", existing.mode or "user").casefold()
    if mode not in {"user", "bot"}:
        console.print("[red]Неизвестный режим, использую user.[/red]")
        mode = "user"

    phone = _ask("Телефон (например +79991234567, можно оставить пустым)", existing.phone)
    bot_token = existing.bot_token
    if mode == "bot":
        while not bot_token:
            bot_token = _ask("TG_BOT_TOKEN (токен от @BotFather)", existing.bot_token, secret=True)
            if not bot_token:
                console.print("[red]Для режима bot токен обязателен.[/red]")
    else:
        bot_token = _ask(
            "TG_BOT_TOKEN (необязательно, Enter — оставить, - — очистить)",
            existing.bot_token,
            secret=True,
        )

    session_raw = _ask("Файл сессии", str(existing.session_file))
    download_raw = _ask("Папка для скачивания", str(existing.download_dir))

    settings = Settings(
        api_id=api_id,
        api_hash=api_hash.strip(),
        phone=phone or None,
        password=existing.password,
        mode=mode,
        bot_token=bot_token or None,
        session_file=_resolve_local_path(session_raw),
        download_dir=_resolve_local_path(download_raw),
        env_file=target,
        flood_sleep_threshold=existing.flood_sleep_threshold,
    )
    settings.validate()
    target = write_env_file(target, settings)
    settings.env_file = target
    settings.ensure_directories()

    console.print(f"\n[green]✅ Конфигурация сохранена:[/green] {escape(str(target))}")
    console.print(f"[dim]Сессия: {escape(str(settings.session_path))}[/dim]")
    console.print("[dim]Не публикуйте .env и .session — это доступ к аккаунту.[/dim]")

    if login:
        _login_only(settings)
    elif auto:
        console.print("[dim]Продолжаю выполнение команды...[/dim]")
    else:
        console.print("Теперь выполните вход: [bold]tg login[/bold]")
    return settings


def _login_only(settings: Settings) -> None:
    async def go() -> None:
        api = TelegramAPI(settings)
        try:
            await api.start(interactive=True)
            me = await api.get_me()
            console.print(f"[green]✅ Вход выполнен:[/green] {escape(str(me.get('title') or me.get('id')))}")
        finally:
            await api.close()

    asyncio.run(go())


def ensure_settings(args: argparse.Namespace) -> Settings:
    overrides = {
        "session_file": getattr(args, "session", None),
        "download_dir": getattr(args, "download_dir", None),
    }
    settings = Settings.from_env(getattr(args, "env", None), overrides=overrides)
    try:
        settings.validate()
    except ConfigError:
        if args.command == "setup":
            raise
        if args.no_input or not sys.stdin.isatty():
            raise
        console.print("[yellow]Конфигурация ещё не готова — запускаю настройку.[/yellow]\n")
        settings = run_setup(settings.env_file, force=True, login=False, auto=True)
    return settings


async def _dispatch(settings: Settings, args: argparse.Namespace) -> int:
    api = TelegramAPI(settings)
    try:
        await api.start(interactive=not args.no_input and sys.stdin.isatty())
        handler = _HANDLERS.get(args.command)
        if handler is None:
            raise TGError(f"Неизвестная команда: {args.command}")
        return await handler(api, args)
    finally:
        await api.close()


_HANDLERS = {
    "me": cmd_me,
    "login": cmd_login,
    "chats": cmd_chats,
    "read": cmd_read,
    "send": cmd_send,
    "send-file": cmd_send_file,
    "download": cmd_download,
    "download-message": cmd_download_message,
    "download-chat": cmd_download_chat,
    "search": cmd_search,
    "info": cmd_info,
    "participants": cmd_participants,
    "forward": cmd_forward,
    "delete": cmd_delete,
    "edit": cmd_edit,
    "mark-read": cmd_mark_read,
    "pin": cmd_pin,
    "unpin": cmd_unpin,
    "join": cmd_join,
    "leave": cmd_leave,
    "create-group": cmd_create_group,
    "export": cmd_export,
    "watch": cmd_watch,
}


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Выводить JSON")
    parser.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS, help="Меньше вывода")
    parser.add_argument("--no-input", action="store_true", default=argparse.SUPPRESS, help="Не запрашивать ввод")
    parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="Показывать traceback")
    parser.add_argument("--env", metavar="FILE", default=argparse.SUPPRESS, help="Путь к .env")
    parser.add_argument("--session", metavar="FILE", default=argparse.SUPPRESS, help="Путь к файлу сессии")
    parser.add_argument("--download-dir", metavar="DIR", default=argparse.SUPPRESS, help="Папка скачивания")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_flags(common)

    parser = argparse.ArgumentParser(
        prog="tg",
        description="TG Tools — Telegram через официальный API (MTProto/Telethon).",
        epilog=(
            "Примеры:\n"
            "  tg chats\n"
            "  tg read @durov --limit 20\n"
            "  tg send @username \"Привет!\"\n"
            "  tg send-file @username photo.jpg --caption \"Смотри\"\n"
            "  tg download https://t.me/channel/123 -o downloads\n"
            "  tg download-chat @channel --type photo,video --limit 100\n"
            "  tg watch @channel\n"
            "  tg export @channel -o messages.jsonl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_flags(parser)
    parser.add_argument("--version", action="version", version=f"TG Tools {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    def add(name: str, help_text: str, *, parents: bool = True) -> argparse.ArgumentParser:
        return sub.add_parser(
            name,
            help=help_text,
            description=help_text,
            parents=[common] if parents else [],
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    p = add("setup", "Настроить api_id/api_hash и войти в аккаунт")
    p.add_argument("--force", action="store_true", help="Перезаписать .env без вопроса")
    p.add_argument("--no-login", action="store_true", help="Только сохранить настройки, без входа")

    add("login", "Войти в аккаунт (код придёт в Telegram)")
    add("me", "Показать текущий аккаунт")

    p = add("chats", "Список чатов")
    p.add_argument("--limit", type=int, default=30, help="Сколько чатов показать (0 — все)")
    p.add_argument("--archived", action="store_true", help="Показать архив")
    p.add_argument("--folder", type=int, default=None, help="Папка чатов (folder id)")

    p = add("read", "Прочитать сообщения чата")
    p.add_argument("chat", help="Чат: @username, ссылка, id или название")
    p.add_argument("--limit", type=int, default=20, help="Сколько сообщений (0 — все)")
    p.add_argument("--search", help="Поиск по тексту внутри чата")
    p.add_argument("--since", help="С даты/времени: 2026-10-25, 2h, 7d")
    p.add_argument("--until", help="По дату/время")
    p.add_argument("--reverse", action="store_true", help="От старых к новым")
    p.add_argument("--from", dest="from_user", metavar="USER", help="Только от этого пользователя")
    p.add_argument("--media-only", action="store_true", help="Только сообщения с медиа")
    p.add_argument("--export", metavar="FILE", help="Сохранить в JSONL")

    p = add("send", "Отправить текстовое сообщение")
    p.add_argument("chat", help="Чат")
    p.add_argument("text", nargs="*", help="Текст (если пусто — читается из stdin)")
    p.add_argument("--reply-to", type=int, help="Ответить на сообщение id")
    p.add_argument("--silent", action="store_true", help="Без уведомления")
    p.add_argument("--plain", action="store_true", help="Без Markdown-разметки")
    p.add_argument("--no-preview", action="store_true", help="Не разворачивать ссылки")

    p = add("send-file", "Отправить файл(ы), можно альбом")
    p.add_argument("chat", help="Чат")
    p.add_argument("files", nargs="+", help="Файл или папка")
    p.add_argument("--caption", help="Подпись")
    p.add_argument("--reply-to", type=int, help="Ответить на сообщение id")
    p.add_argument("--silent", action="store_true", help="Без уведомления")
    p.add_argument("--plain", action="store_true", help="Без Markdown-разметки в подписи")

    p = add("download", "Скачать медиа по ссылке на сообщение")
    p.add_argument("link", help="Ссылка https://t.me/.../123 или t.me/c/.../123")
    p.add_argument("-o", "--out", help="Куда сохранить (файл или папка)")
    p.add_argument("--overwrite", action="store_true", help="Перезаписать существующий файл")

    p = add("download-message", "Скачать медиа сообщения по чату и id")
    p.add_argument("chat", help="Чат")
    p.add_argument("message_id", type=int, help="id сообщения")
    p.add_argument("-o", "--out", help="Куда сохранить (файл или папка)")
    p.add_argument("--overwrite", action="store_true", help="Перезаписать существующий файл")

    p = add("download-chat", "Скачать медиа из чата")
    p.add_argument("chat", help="Чат")
    p.add_argument("--limit", type=int, default=100, help="Сколько медиа скачать (0 — все)")
    p.add_argument("--type", dest="media_types", action="append", metavar="TYPE", help="photo,video,document,audio,voice,gif,sticker,video_note,all")
    p.add_argument("-o", "--out", metavar="DIR", help="Папка назначения")
    p.add_argument("--since", help="С даты/времени")
    p.add_argument("--until", help="По дату/время")
    p.add_argument("--overwrite", action="store_true", help="Перезаписывать существующие файлы")

    p = add("search", "Поиск сообщений в чате")
    p.add_argument("chat", help="Чат")
    p.add_argument("query", help="Строка поиска")
    p.add_argument("--limit", type=int, default=50, help="Сколько результатов")
    p.add_argument("--since", help="С даты/времени")
    p.add_argument("--until", help="По дату/время")

    p = add("info", "Информация о чате/пользователе/канале")
    p.add_argument("chat", help="Чат")

    p = add("participants", "Участники группы/канала")
    p.add_argument("chat", help="Чат")
    p.add_argument("--limit", type=int, default=200, help="Сколько участников")
    p.add_argument("--search", help="Поиск по имени/username")

    p = add("forward", "Переслать сообщения")
    p.add_argument("from_chat", help="Откуда")
    p.add_argument("to_chat", help="Куда")
    p.add_argument("ids", nargs="+", help="id сообщений (можно через запятую)")
    p.add_argument("--silent", action="store_true", help="Без уведомления")

    p = add("delete", "Удалить сообщения")
    p.add_argument("chat", help="Чат")
    p.add_argument("ids", nargs="+", help="id сообщений")
    p.add_argument("--keep-for-me", action="store_true", help="Удалить только у себя (не у всех)")
    p.add_argument("--dry-run", action="store_true", help="Показать сообщения, ничего не удаляя")

    p = add("edit", "Изменить текст сообщения")
    p.add_argument("chat", help="Чат")
    p.add_argument("message_id", type=int, help="id сообщения")
    p.add_argument("text", nargs="+", help="Новый текст")
    p.add_argument("--plain", action="store_true", help="Без Markdown-разметки")

    p = add("mark-read", "Отметить чат прочитанным")
    p.add_argument("chat", help="Чат")
    p.add_argument("--max-id", type=int, help="Отметить только до этого id")

    p = add("pin", "Закрепить сообщение")
    p.add_argument("chat", help="Чат")
    p.add_argument("message_id", type=int, help="id сообщения")
    p.add_argument("--notify", action="store_true", help="С уведомлением")

    p = add("unpin", "Открепить сообщение")
    p.add_argument("chat", help="Чат")
    p.add_argument("message_id", type=int, nargs="?", help="id сообщения (пусто — все)")

    p = add("join", "Вступить в канал/группу")
    p.add_argument("link", help="@username или ссылка-приглашение")

    p = add("leave", "Выйти из группы/канала")
    p.add_argument("chat", help="Чат")

    p = add("create-group", "Создать группу")
    p.add_argument("title", help="Название")
    p.add_argument("users", nargs="+", help="@username или id участников")

    p = add("export", "Экспортировать историю в JSONL")
    p.add_argument("chat", help="Чат")
    p.add_argument("--limit", type=int, default=0, help="Сколько сообщений (0 — все)")
    p.add_argument("--since", help="С даты/времени")
    p.add_argument("--until", help="По дату/время")
    p.add_argument("-o", "--out", metavar="FILE", help="Куда сохранить JSONL")

    p = add("watch", "Слушать новые сообщения в реальном времени")
    p.add_argument("chats", nargs="*", help="Чаты (пусто — все)")
    p.add_argument("--limit", type=int, default=0, help="Остановиться после N сообщений (0 — бесконечно)")
    p.add_argument("--timeout", type=float, help="Выйти, если N секунд нет сообщений")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--incoming", action="store_true", help="Только входящие")
    group.add_argument("--outgoing", action="store_true", help="Только исходящие")

    add("version", "Показать версию")

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    try:
        if args.command == "version":
            console.print(f"TG Tools {__version__}")
            return 0

        if args.command == "setup":
            run_setup(
                getattr(args, "env", None),
                force=args.force,
                login=not args.no_login,
            )
            return 0

        settings = ensure_settings(args)
        return asyncio.run(_dispatch(settings, args))
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Остановлено.[/yellow]")
        return 130
    except FloodWaitError as exc:
        err_console.print(
            f"[red]Telegram просит подождать {exc.seconds} секунд.[/red] "
            "Не запускайте команду повторно сразу."
        )
        return 2
    except (ConfigError, TGError) as exc:
        err_console.print(f"[red]Ошибка:[/red] {escape(str(exc))}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return 1
    except RPCError as exc:
        err_console.print(
            f"[red]Telegram API:[/red] {escape(exc.__class__.__name__)}: {escape(str(exc))}"
        )
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return 1
    except ValueError as exc:
        err_console.print(f"[red]Ошибка:[/red] {escape(str(exc))}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return 1
    except Exception as exc:
        err_console.print(f"[red]Ошибка:[/red] {escape(str(exc))}")
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            err_console.print("[dim]Запустите с --verbose, чтобы увидеть traceback.[/dim]")
        return 1
