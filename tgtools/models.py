"""Преобразование объектов Telethon в обычные словари для JSON/CLI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from telethon.tl import types
from telethon.utils import get_display_name

from .utils import MEDIA_TYPES


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def display_name(entity: Any, fallback: str = "") -> str:
    if entity is None:
        return fallback
    try:
        name = get_display_name(entity)
    except Exception:
        name = None
    if name:
        return str(name)
    for attribute in ("title", "first_name", "username"):
        value = getattr(entity, attribute, None)
        if value:
            return str(value)
    entity_id = getattr(entity, "id", None)
    return fallback or (str(entity_id) if entity_id is not None else "?")


def entity_type(entity: Any) -> str:
    if isinstance(entity, types.User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, (types.Chat, types.ChatForbidden, types.ChatEmpty)):
        return "group"
    if isinstance(entity, types.Channel):
        return "channel" if getattr(entity, "broadcast", False) else "supergroup"
    if isinstance(entity, types.ChannelForbidden):
        return "channel"
    return "unknown"


def entity_to_dict(entity: Any, *, full: Any = None, participants_count: int | None = None) -> dict[str, Any]:
    if entity is None:
        return {}

    result: dict[str, Any] = {
        "id": getattr(entity, "id", None),
        "type": entity_type(entity),
        "title": display_name(entity),
        "username": getattr(entity, "username", None),
    }

    if isinstance(entity, types.User):
        result.update(
            {
                "first_name": getattr(entity, "first_name", None),
                "last_name": getattr(entity, "last_name", None),
                "phone": getattr(entity, "phone", None),
                "bot": bool(getattr(entity, "bot", False)),
                "verified": bool(getattr(entity, "verified", False)),
                "premium": bool(getattr(entity, "premium", False)),
                "deleted": bool(getattr(entity, "deleted", False)),
                "restricted": bool(getattr(entity, "restricted", False)),
            }
        )
        if getattr(entity, "status", None) is not None:
            result["status"] = type(entity.status).__name__

    if isinstance(entity, types.Channel):
        result.update(
            {
                "megagroup": bool(getattr(entity, "megagroup", False)),
                "broadcast": bool(getattr(entity, "broadcast", False)),
                "verified": bool(getattr(entity, "verified", False)),
                "scam": bool(getattr(entity, "scam", False)),
                "fake": bool(getattr(entity, "fake", False)),
                "restricted": bool(getattr(entity, "restricted", False)),
            }
        )
        if getattr(entity, "participants_count", None) is not None:
            result["participants_count"] = entity.participants_count
        if getattr(entity, "linked_chat_id", None) is not None:
            result["linked_chat_id"] = entity.linked_chat_id

    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        result["participants_count"] = getattr(entity, "participants_count", None)
        result["deactivated"] = bool(getattr(entity, "deactivated", False))

    if participants_count is not None:
        result["participants_count"] = participants_count

    if full is not None:
        about = getattr(full, "about", None)
        if about:
            result["about"] = about
        if getattr(full, "participants_count", None) is not None:
            result["participants_count"] = full.participants_count
        if getattr(full, "online_count", None) is not None:
            result["online_count"] = full.online_count
        if getattr(full, "common_chats_count", None) is not None:
            result["common_chats_count"] = full.common_chats_count
        if getattr(full, "pinned_msg_id", None) is not None:
            result["pinned_msg_id"] = full.pinned_msg_id
        if getattr(full, "linked_chat_id", None) is not None:
            result["linked_chat_id"] = full.linked_chat_id
        if getattr(full, "phone", None) is not None and "phone" not in result:
            result["phone"] = full.phone

    return result


def _file_info(message: Any) -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        file = message.file
    except Exception:
        file = None
    if not file:
        return info

    for source, key in (
        ("name", "file_name"),
        ("size", "size"),
        ("mime_type", "mime_type"),
        ("ext", "ext"),
        ("duration", "duration"),
        ("width", "width"),
        ("height", "height"),
    ):
        value = getattr(file, source, None)
        if value not in (None, ""):
            info[key] = value
    return info


def _media_kind(message: Any) -> str | None:
    try:
        if getattr(message, "photo", None):
            return "photo"
        if getattr(message, "sticker", None):
            return "sticker"
        if getattr(message, "gif", None):
            return "gif"
        if getattr(message, "video_note", None):
            return "video_note"
        if getattr(message, "voice", None):
            return "voice"
        if getattr(message, "video", None):
            return "video"
        if getattr(message, "audio", None):
            return "audio"
        if getattr(message, "document", None):
            return "document"
        if getattr(message, "poll", None):
            return "poll"
        if getattr(message, "geo", None):
            return "location"
        if getattr(message, "contact", None):
            return "contact"
        if getattr(message, "dice", None):
            return "dice"
        if getattr(message, "game", None):
            return "game"
        if getattr(message, "web_preview", None):
            return "webpage"
        if getattr(message, "action", None):
            return "service"
    except Exception:
        return None
    return None


def media_info(message: Any) -> dict[str, Any] | None:
    kind = _media_kind(message)
    if not kind:
        return None

    info: dict[str, Any] = {"type": kind}

    if kind in {"photo", "video", "audio", "voice", "document", "gif", "sticker", "video_note"}:
        info.update(_file_info(message))

    if kind == "poll":
        poll = message.poll
        info.update(
            {
                "question": getattr(getattr(poll, "poll", None), "question", None),
                "closed": getattr(poll, "closed", None),
                "total_voters": getattr(poll, "total_voters", None),
            }
        )
    elif kind == "location":
        geo = message.geo
        info.update({"lat": getattr(geo, "lat", None), "long": getattr(geo, "long", None)})
    elif kind == "contact":
        contact = message.contact
        info.update(
            {
                "first_name": getattr(contact, "first_name", None),
                "last_name": getattr(contact, "last_name", None),
                "phone": getattr(contact, "phone", None),
            }
        )
    elif kind == "webpage":
        preview = message.web_preview
        info.update(
            {
                "url": getattr(preview, "url", None),
                "title": getattr(preview, "title", None),
                "site_name": getattr(preview, "site_name", None),
            }
        )
    elif kind == "service":
        info["action"] = type(message.action).__name__

    return {key: value for key, value in info.items() if value not in (None, "")}


def message_link(message: Any, chat: Any = None) -> str | None:
    chat = chat if chat is not None else getattr(message, "chat", None)
    message_id = getattr(message, "id", None)
    if not chat or not message_id:
        return None

    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"

    if isinstance(chat, (types.Channel, types.ChannelForbidden)) and (
        getattr(chat, "megagroup", False) or getattr(chat, "broadcast", False)
    ):
        return f"https://t.me/c/{chat.id}/{message_id}"
    return None


def message_to_dict(
    message: Any,
    *,
    chat: Any = None,
    sender: Any = None,
) -> dict[str, Any]:
    chat = chat if chat is not None else getattr(message, "chat", None)
    sender = sender if sender is not None else getattr(message, "sender", None)
    media = media_info(message)

    sender_id = getattr(message, "sender_id", None)
    chat_id = getattr(message, "chat_id", None)
    reply_to = getattr(message, "reply_to_msg_id", None)

    result: dict[str, Any] = {
        "id": getattr(message, "id", None),
        "date": isoformat(getattr(message, "date", None)),
        "edit_date": isoformat(getattr(message, "edit_date", None)),
        "chat_id": chat_id,
        "chat_title": display_name(chat) if chat else None,
        "chat_username": getattr(chat, "username", None) if chat else None,
        "sender_id": sender_id,
        "sender_name": display_name(sender) if sender else None,
        "sender_username": getattr(sender, "username", None) if sender else None,
        "text": getattr(message, "message", None) or "",
        "out": bool(getattr(message, "out", False)),
        "post": bool(getattr(message, "post", False)),
        "reply_to": reply_to,
        "topic_id": getattr(getattr(message, "reply_to", None), "reply_to_top_id", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "grouped_id": getattr(message, "grouped_id", None),
        "pinned": bool(getattr(message, "pinned", False)),
        "has_media": media is not None and media.get("type") in MEDIA_TYPES,
        "media": media,
        "link": message_link(message, chat),
    }

    if getattr(message, "via_bot_id", None):
        result["via_bot_id"] = message.via_bot_id

    return result


def dialog_to_dict(dialog: Any) -> dict[str, Any]:
    entity = dialog.entity
    last = getattr(dialog, "message", None)
    last_media = media_info(last) if last is not None else None

    return {
        "id": dialog.id,
        "entity_id": getattr(entity, "id", None),
        "title": dialog.name,
        "type": entity_type(entity),
        "username": getattr(entity, "username", None),
        "phone": getattr(entity, "phone", None) if isinstance(entity, types.User) else None,
        "unread": getattr(dialog, "unread_count", 0) or 0,
        "unread_mentions": getattr(dialog, "unread_mentions_count", 0) or 0,
        "pinned": bool(getattr(dialog, "pinned", False)),
        "archived": bool(getattr(dialog, "archived", False)),
        "folder_id": getattr(dialog, "folder_id", None),
        "last_message": {
            "id": getattr(last, "id", None),
            "date": isoformat(getattr(last, "date", None)),
            "text": getattr(last, "message", None) or "",
            "out": bool(getattr(last, "out", False)),
            "media_type": last_media.get("type") if last_media else None,
        }
        if last is not None
        else None,
    }
