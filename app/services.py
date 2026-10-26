"""Общая логика: отправка карточек, темы, разбор сообщений, поиск владельца."""
from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from typing import Any, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, Chat, Message

from .config import Config
from .db import Database

log = logging.getLogger(__name__)

# тип медиа -> (метод бота, имя параметра с файлом, расширение для перезагрузки)
MEDIA_METHODS = {
    "photo": ("send_photo", "photo", "jpg"),
    "video": ("send_video", "video", "mp4"),
    "animation": ("send_animation", "animation", "mp4"),
    "document": ("send_document", "document", "bin"),
    "voice": ("send_voice", "voice", "ogg"),
    "audio": ("send_audio", "audio", "mp3"),
    "video_note": ("send_video_note", "video_note", "mp4"),
    "sticker": ("send_sticker", "sticker", "webp"),
}
NO_CAPTION = {"video_note", "sticker"}
CAPTION_LIMIT = 1000  # у подписи лимит 1024, оставляем запас


# ---------------------------------------------------------------- утилиты
def to_ts(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return int(time.time())


def chat_name_of(chat: Chat) -> str:
    full = " ".join(p for p in (chat.first_name, chat.last_name) if p)
    return full or chat.title or chat.username or str(chat.id)


def chat_label(chat: Chat) -> str:
    return f"@{chat.username}" if chat.username else chat_name_of(chat)


def extract(message: Message) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Возвращает (текст/подпись, тип медиа, file_id, file_unique_id)."""
    text = message.text or message.caption or ""
    if message.photo:
        p = message.photo[-1]
        return text, "photo", p.file_id, p.file_unique_id
    # animation раньше document: у GIF заполнены оба поля
    for attr, kind in (
        ("animation", "animation"), ("video", "video"), ("document", "document"),
        ("voice", "voice"), ("audio", "audio"), ("video_note", "video_note"),
        ("sticker", "sticker"),
    ):
        obj = getattr(message, attr, None)
        if obj is not None:
            return text, kind, obj.file_id, obj.file_unique_id
    return text, None, None, None


def should_notify(owner: dict, kind: str, is_own: bool, peer_is_bot: bool) -> bool:
    """kind: 'edit' | 'delete'. Историю это не затрагивает: события пишутся всегда."""
    if peer_is_bot and not owner["notif_bots"]:
        return False
    if is_own:
        return bool(owner["notif_self"])
    return bool(owner["notif_edit"] if kind == "edit" else owner["notif_delete"])


# ---------------------------------------------------------------- владелец
async def resolve_owner(bot: Bot, db: Database, connection_id: Optional[str]) -> Optional[dict]:
    if not connection_id:
        return None
    owner = await db.get_owner_by_connection(connection_id)
    if owner:
        return owner if owner["is_active"] else None
    try:
        conn = await bot.get_business_connection(connection_id)
    except Exception:  # noqa: BLE001 - соединение могло быть удалено
        log.warning("Не удалось получить business connection %s", connection_id)
        return None
    u = conn.user
    await db.upsert_owner(u.id, conn.user_chat_id, conn.id, u.first_name, u.last_name,
                          u.username, bool(conn.is_enabled))
    owner = await db.get_owner(u.id)
    return owner if owner and owner["is_active"] else None


async def remember(db: Database, owner: dict, message: Message) -> None:
    """Сохраняет копию сообщения, чтобы потом показать его при удалении/изменении."""
    text, media_type, file_id, unique_id = extract(message)
    user = message.from_user
    is_own = bool(user and user.id == owner["user_id"])
    chat = message.chat
    if user and not is_own:
        await db.upsert_chat(owner["user_id"], chat.id, chat_name_of(chat), chat.username,
                             bool(user.is_bot))
    await db.save_message(
        owner["user_id"], chat.id, message.message_id,
        user.id if user else None,
        user.full_name if user else chat_name_of(chat),
        user.username if user else None,
        is_own, text, media_type, file_id, unique_id, to_ts(message.date),
    )


# ---------------------------------------------------------------- темы
async def ensure_topics(bot: Bot, db: Database, cfg: Config, owner: dict) -> dict:
    """Создаёт вкладки «Изменённые» и «Управление» в личке бота (если клиент это умеет)."""
    if not cfg.use_topics or owner["topics_tried"]:
        return owner
    events = menu = None
    try:
        events = (await bot.create_forum_topic(chat_id=owner["chat_id"],
                                               name="✏️ Изменённые")).message_thread_id
        menu = (await bot.create_forum_topic(chat_id=owner["chat_id"],
                                             name="🏠 Управление")).message_thread_id
    except Exception as exc:  # noqa: BLE001
        log.info("Темы в личке недоступны (%s): работаю без вкладок", exc)
        events = menu = None
    await db.set_topics(owner["user_id"], events, menu)
    return await db.get_owner(owner["user_id"]) or owner


# ---------------------------------------------------------------- отправка
def _is_parse_error(exc: TelegramBadRequest) -> bool:
    msg = str(exc).lower()
    return "parse" in msg or "entities" in msg


def _simplify(html_text: str) -> str:
    """Запасной вариант разметки, если клиент/сервер не принял <pre> внутри цитаты."""
    return html_text.replace("<pre>", "<code>").replace("</pre>", "</code>")


async def _send_media(bot: Bot, chat_id: int, media_type: str, file_id: str,
                      caption: Optional[str], thread_id: Optional[int]) -> bool:
    method, param, ext = MEDIA_METHODS[media_type]
    call = getattr(bot, method)
    kwargs: dict[str, Any] = {"chat_id": chat_id, "message_thread_id": thread_id}
    if caption and media_type not in NO_CAPTION:
        kwargs["caption"] = caption
    try:
        await call(**{param: file_id}, **kwargs)
        return True
    except TelegramBadRequest as exc:
        if _is_parse_error(exc):
            raise
        log.info("Отправка по file_id не удалась (%s), пробую перезагрузить файл", exc)
    try:
        buf = io.BytesIO()
        await bot.download(file_id, destination=buf)
        data = BufferedInputFile(buf.getvalue(), filename=f"saved.{ext}")
        await call(**{param: data}, **kwargs)
        return True
    except TelegramBadRequest as exc:
        if _is_parse_error(exc):
            raise
        log.warning("Не удалось отправить вложение: %s", exc)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось скачать/отправить вложение")
    return False


async def _deliver_once(bot: Bot, chat_id: int, text: str, media_type: Optional[str],
                        file_id: Optional[str], thread_id: Optional[int], markup: Any) -> None:
    if not (media_type and file_id):
        await bot.send_message(chat_id, text, message_thread_id=thread_id, reply_markup=markup)
        return
    if media_type not in NO_CAPTION and len(text) <= CAPTION_LIMIT:
        if await _send_media(bot, chat_id, media_type, file_id, text, thread_id):
            return
        await bot.send_message(chat_id, text + "\n\n⚠️ Вложение недоступно на серверах Telegram.",
                               message_thread_id=thread_id, reply_markup=markup)
        return
    await bot.send_message(chat_id, text, message_thread_id=thread_id, reply_markup=markup)
    if not await _send_media(bot, chat_id, media_type, file_id, None, thread_id):
        await bot.send_message(chat_id, "⚠️ Вложение недоступно на серверах Telegram.",
                               message_thread_id=thread_id)


async def deliver(bot: Bot, chat_id: int, text: str, *, media_type: Optional[str] = None,
                  file_id: Optional[str] = None, thread_id: Optional[int] = None,
                  reply_markup: Any = None) -> bool:
    """Отправляет карточку (с вложением, если есть). Сама подстраивается под ошибки разметки и тем."""
    variants: list[tuple[str, Optional[int]]] = [(text, thread_id), (_simplify(text), thread_id)]
    if thread_id:
        variants.append((_simplify(text), None))
    for txt, th in variants:
        try:
            await _deliver_once(bot, chat_id, txt, media_type, file_id, th, reply_markup)
            return True
        except TelegramForbiddenError:
            log.warning("Бот заблокирован пользователем %s", chat_id)
            return False
        except TelegramBadRequest as exc:
            log.warning("Отправка не удалась (%s), пробую запасной вариант", exc)
    log.error("Не удалось доставить сообщение в чат %s", chat_id)
    return False
