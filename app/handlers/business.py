"""События бизнес-аккаунта: подключение, новые/изменённые/удалённые сообщения, команды юзербота."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message

from .. import texts as T
from ..config import Config
from ..db import Database
from ..keyboards import main_menu
from ..services import (
    chat_label, chat_name_of, deliver, ensure_topics, extract, remember,
    resolve_owner, should_notify, to_ts,
)

log = logging.getLogger(__name__)
router = Router(name="business")

# сообщения, которые бот сам сейчас редактирует (эффект печатной машинки):
# их правки не считаются событиями
_BUSY: set[tuple[int, int, int]] = set()


# ======================================================================
# Подключение / отключение бота в Telegram Business
# ======================================================================
@router.business_connection()
async def on_connection(conn: BusinessConnection, bot: Bot, db: Database, cfg: Config) -> None:
    u = conn.user
    enabled = bool(conn.is_enabled)
    await db.upsert_owner(u.id, conn.user_chat_id, conn.id, u.first_name, u.last_name,
                          u.username, enabled)
    owner = await db.get_owner(u.id)
    if owner is None:
        return
    if enabled:
        owner = await ensure_topics(bot, db, cfg, owner)
    await deliver(bot, owner["chat_id"], T.connection_status(enabled),
                  thread_id=owner["topic_menu"] or None, reply_markup=main_menu())


# ======================================================================
# Новые сообщения
# ======================================================================
@router.business_message()
async def on_message(message: Message, bot: Bot, db: Database, cfg: Config) -> None:
    owner = await resolve_owner(bot, db, message.business_connection_id)
    if owner is None:
        return
    chat = message.chat
    if chat.type != "private":
        return  # юзербот и мониторинг работают только в личных диалогах
    is_own = bool(message.from_user and message.from_user.id == owner["user_id"])

    if is_own:
        if await handle_command(message, bot, db, cfg, owner):
            return  # команды не сохраняем: их удаление не должно давать событие
        await maybe_save_one_time(message, bot, db, cfg, owner)
    elif await db.is_muted(owner["user_id"], chat.id):
        await try_delete(bot, message.business_connection_id, [message.message_id])
        return

    await remember(db, owner, message)


# ======================================================================
# Изменённые сообщения
# ======================================================================
@router.edited_business_message()
async def on_edit(message: Message, bot: Bot, db: Database, cfg: Config) -> None:
    owner = await resolve_owner(bot, db, message.business_connection_id)
    if owner is None or message.chat.type != "private":
        return
    chat = message.chat
    key = (owner["user_id"], chat.id, message.message_id)
    if key in _BUSY:
        return

    new_text, _mtype, _fid, new_unique = extract(message)
    row = await db.get_message(*key)
    if row is None:
        # прошлой версии нет (сообщение пришло до подключения): запоминаем текущую
        await remember(db, owner, message)
        return
    if (row["text"] or "") == new_text and (row["file_unique_id"] or "") == (new_unique or ""):
        return  # правка без изменения содержимого (например, реакция)

    ts = to_ts(message.edit_date)
    user = message.from_user
    who = T.who(
        user.full_name if user else row["sender_name"],
        user.username if user else row["sender_username"],
        user.id if user else row["sender_id"],
    )
    media_changed = (row["file_unique_id"] or "") != (new_unique or "")
    card = T.card_edit(T.fmt_dt(cfg.tz, ts), T.where(chat_name_of(chat), chat.id), who,
                       message.message_id, row["text"] or "", new_text)
    old_media = row["media_type"] if media_changed else None
    old_file = row["file_id"] if media_changed else None

    await db.add_event(owner["user_id"], "edit", ts, chat_label(chat), card, old_media, old_file)
    await remember(db, owner, message)

    chat_row = await db.get_chat(owner["user_id"], chat.id)
    peer_is_bot = bool(chat_row and chat_row["is_bot"])
    if should_notify(owner, "edit", bool(row["is_own"]), peer_is_bot):
        await deliver(bot, owner["chat_id"], card, media_type=old_media, file_id=old_file,
                      thread_id=owner["topic_events"] or None)


# ======================================================================
# Удалённые сообщения
# ======================================================================
@router.deleted_business_messages()
async def on_deleted(event: BusinessMessagesDeleted, bot: Bot, db: Database, cfg: Config) -> None:
    owner = await resolve_owner(bot, db, event.business_connection_id)
    if owner is None or event.chat.type != "private":
        return
    chat = event.chat
    now = int(time.time())
    chat_row = await db.get_chat(owner["user_id"], chat.id)
    peer_is_bot = bool(chat_row and chat_row["is_bot"])

    for message_id in sorted(event.message_ids):
        row = await db.get_message(owner["user_id"], chat.id, message_id)
        if row is None:
            continue  # бот не видел это сообщение, показать нечего
        who = T.who(row["sender_name"] or chat_name_of(chat), row["sender_username"],
                    row["sender_id"])
        card = T.card_delete(T.fmt_dt(cfg.tz, now), T.where(chat_name_of(chat), chat.id), who,
                             row["text"] or "", row["media_type"])
        await db.add_event(owner["user_id"], "delete", now, chat_label(chat), card,
                           row["media_type"], row["file_id"])
        await db.delete_message(owner["user_id"], chat.id, message_id)

        if should_notify(owner, "delete", bool(row["is_own"]), peer_is_bot):
            await deliver(bot, owner["chat_id"], card, media_type=row["media_type"],
                          file_id=row["file_id"], thread_id=owner["topic_events"] or None)


# ======================================================================
# Одноразовые медиа: сохраняем при ответе на них
# ======================================================================
async def maybe_save_one_time(message: Message, bot: Bot, db: Database, cfg: Config,
                              owner: dict) -> None:
    replied = message.reply_to_message
    if replied is None or not owner["spy_on"]:
        return
    _caption, media_type, file_id, _unique = extract(replied)
    if not (media_type and file_id):
        return
    chat = message.chat
    stored = await db.get_message(owner["user_id"], chat.id, replied.message_id)
    # обычное медиа бот уже видел при получении: без режима «любое медиа» его пропускаем
    if stored and stored["file_id"] and not owner["spy_any"]:
        return
    ref = f"{chat.id}:{replied.message_id}"
    if await db.has_event_ref(owner["user_id"], ref):
        return

    now = int(time.time())
    author = replied.from_user
    who = T.who(author.full_name if author else chat_name_of(chat),
                author.username if author else None, author.id if author else None)
    caption = replied.caption or ""
    card = T.card_spy(T.fmt_dt(cfg.tz, now), T.where(chat_name_of(chat), chat.id), who,
                      media_type, caption)
    await db.add_event(owner["user_id"], "spy", now, chat_label(chat), card, media_type,
                       file_id, ref)
    await deliver(bot, owner["chat_id"], card, media_type=media_type, file_id=file_id,
                  thread_id=owner["topic_events"] or None)


# ======================================================================
# Команды юзербота (.help .mute .type .clock)
# ======================================================================
async def try_delete(bot: Bot, connection_id: Optional[str], ids: list[int]) -> bool:
    try:
        await bot.delete_business_messages(business_connection_id=connection_id, message_ids=ids)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось удалить сообщения %s: %s", ids, exc)
        return False


async def reply_owner(bot: Bot, owner: dict, text: str) -> None:
    await deliver(bot, owner["chat_id"], text, thread_id=owner["topic_menu"] or None)


async def handle_command(message: Message, bot: Bot, db: Database, cfg: Config,
                         owner: dict) -> bool:
    text = (message.text or "").strip()
    if not text.startswith("."):
        return False
    command, _, arg = text.partition(" ")
    command = command.lower()
    arg = arg.strip()
    chat = message.chat
    conn_id = message.business_connection_id

    if command == ".help":
        await try_delete(bot, conn_id, [message.message_id])
        await reply_owner(bot, owner, T.USERBOT_HELP)
        return True

    if command == ".mute":
        enabled = await db.toggle_mute(owner["user_id"], chat.id)
        deleted = await try_delete(bot, conn_id, [message.message_id])
        name = T.esc(chat_name_of(chat))
        note = (f"🔇 Режим игнора <b>включён</b>: {name}. Новые сообщения собеседника "
                "будут удаляться." if enabled else f"🔔 Режим игнора <b>выключен</b>: {name}.")
        if not deleted:
            note += "\n\n⚠️ Не удалось удалить команду: проверьте права бота на управление сообщениями."
        await reply_owner(bot, owner, note)
        return True

    if command == ".type":
        if not arg:
            return False
        key = (owner["user_id"], chat.id, message.message_id)
        _BUSY.add(key)
        asyncio.create_task(typewriter(bot, conn_id, chat.id, message.message_id, arg, key))
        return True

    if command == ".clock":
        await try_delete(bot, conn_id, [message.message_id])
        await toggle_clock(bot, db, owner, arg)
        return True

    return False


async def _edit_plain(bot: Bot, conn_id: Optional[str], chat_id: int, message_id: int,
                      text: str) -> None:
    while True:
        try:
            await bot.edit_message_text(text=text, business_connection_id=conn_id,
                                        chat_id=chat_id, message_id=message_id, parse_mode=None)
            return
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.5)
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
            return


async def typewriter(bot: Bot, conn_id: Optional[str], chat_id: int, message_id: int,
                     text: str, key: tuple[int, int, int]) -> None:
    """Печатает текст по кусочкам, редактируя исходное сообщение с командой."""
    try:
        text = text[:1000]
        total = len(text)
        steps = min(total, 24)
        for i in range(1, steps + 1):
            end = -(-total * i // steps)  # потолок деления
            cursor = "▌" if i < steps else ""
            await _edit_plain(bot, conn_id, chat_id, message_id, text[:end] + cursor)
            if i < steps:
                await asyncio.sleep(0.35)
    except Exception:  # noqa: BLE001
        log.exception("Эффект печатной машинки прервался")
    finally:
        # небольшая задержка: последнее обновление об изменении ещё может прилететь
        await asyncio.sleep(2)
        _BUSY.discard(key)


async def toggle_clock(bot: Bot, db: Database, owner: dict, arg: str) -> None:
    if owner["clock_on"] and not arg:
        await db.set_clock(owner["user_id"], False)
        base = owner["clock_base"] or owner["first_name"] or ""
        try:
            await bot.set_business_account_name(
                business_connection_id=owner["connection_id"], first_name=base,
                last_name=owner["last_name"])
            await reply_owner(bot, owner, f"🕒 Имя по времени <b>выключено</b>. Имя: {T.esc(base)}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось вернуть имя: %s", exc)
            await reply_owner(bot, owner, "🕒 Имя по времени выключено, но вернуть имя не вышло. "
                              "Проверьте право бота на изменение имени.")
        return
    base = arg or owner["first_name"] or ""
    if not base:
        await reply_owner(bot, owner, "Укажите имя: <code>.clock Имя</code>")
        return
    await db.set_clock(owner["user_id"], True, base[:40])
    await reply_owner(bot, owner, f"🕒 Имя по времени <b>включено</b>: «{T.esc(base[:40])} | ЧЧ:ММ». "
                      "Обновляется раз в минуту.")
