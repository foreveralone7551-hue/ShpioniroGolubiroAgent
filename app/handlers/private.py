"""Личка с ботом: /start, главное меню и все разделы."""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .. import keyboards as K
from .. import texts as T
from ..config import Config
from ..db import Database
from ..services import deliver

log = logging.getLogger(__name__)
router = Router(name="private")
router.message.filter(F.chat.type == "private")

NOTIF_FIELDS = {"self": "notif_self", "edit": "notif_edit",
                "delete": "notif_delete", "bots": "notif_bots"}


# ======================================================================
# Команды и сообщения
# ======================================================================
@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, bot: Bot, db: Database, cfg: Config) -> None:
    await send_entry(message, bot, db, cfg)


@router.message()
async def any_message(message: Message, bot: Bot, db: Database, cfg: Config) -> None:
    await send_entry(message, bot, db, cfg)


async def send_entry(message: Message, bot: Bot, db: Database, cfg: Config) -> None:
    user = message.from_user
    owner = await db.get_owner(user.id) if user else None
    if owner and owner["is_active"]:
        # если в личке есть вкладки, меню живёт во вкладке «Управление»
        thread = message.message_thread_id or owner["topic_menu"] or None
        await deliver(bot, message.chat.id, T.main_menu(user.first_name), thread_id=thread,
                      reply_markup=K.main_menu())
        return
    await message.answer(T.info(cfg.bot_username, cfg.channel))


# ======================================================================
# Кнопки
# ======================================================================
async def show(cb: CallbackQuery, text: str, markup: Optional[InlineKeyboardMarkup]) -> None:
    msg = cb.message
    if not isinstance(msg, Message):
        await cb.answer()
        return
    try:
        await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise
    await cb.answer()


async def render_history(cb: CallbackQuery, db: Database, cfg: Config, owner: dict,
                         page: int) -> None:
    total = await db.count_events(owner["user_id"])
    if total == 0:
        await show(cb, T.HISTORY_EMPTY, K.back_to_menu("⬅️ Назад в меню"))
        return
    pages = max(1, math.ceil(total / K.PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    events = await db.list_events(owner["user_id"], K.PAGE_SIZE, page * K.PAGE_SIZE)
    await show(cb, T.history_title(page, pages), K.history_kb(events, page, pages, cfg.tz))


@router.callback_query()
async def on_callback(cb: CallbackQuery, bot: Bot, db: Database, cfg: Config) -> None:
    owner = await db.get_owner(cb.from_user.id)
    if not owner or not owner["is_active"]:
        await cb.answer(T.NOT_CONNECTED, show_alert=True)
        return
    action, _, arg = (cb.data or "").partition(":")

    if action == "menu":
        await route_menu(cb, db, cfg, owner, arg)
    elif action == "notif":
        field = NOTIF_FIELDS.get(arg)
        if field:
            await db.toggle_flag(owner["user_id"], field)
        owner = await db.get_owner(owner["user_id"]) or owner
        await show(cb, T.NOTIFICATIONS, K.notifications_kb(owner))
    elif action == "spy":
        if arg in ("on", "any"):
            await db.toggle_flag(owner["user_id"], f"spy_{arg}")
        owner = await db.get_owner(owner["user_id"]) or owner
        await show(cb, T.SPY, K.spy_kb(owner))
    elif action == "info" and arg == "spy":
        await show(cb, T.SPY_HOWTO, K.spy_howto_kb())
    elif action == "ub" and arg == "help":
        await show(cb, T.USERBOT_HELP, K.userbot_help_kb())
    elif action == "hist":
        await render_history(cb, db, cfg, owner, int(arg or 0))
    elif action == "ev":
        await send_event(cb, bot, db, owner, int(arg))
    else:
        await cb.answer()


async def route_menu(cb: CallbackQuery, db: Database, cfg: Config, owner: dict, arg: str) -> None:
    if arg == "main":
        await show(cb, T.main_menu(cb.from_user.first_name), K.main_menu())
    elif arg == "profile":
        deleted = await db.count_events(owner["user_id"], "delete")
        edited = await db.count_events(owner["user_id"], "edit")
        seconds = int(time.time()) - int(owner["connected_at"])
        await show(cb, T.profile(deleted, edited, seconds), K.profile_kb())
    elif arg == "notif":
        await show(cb, T.NOTIFICATIONS, K.notifications_kb(owner))
    elif arg == "spy":
        await show(cb, T.SPY, K.spy_kb(owner))
    elif arg == "userbot":
        await show(cb, T.USERBOT, K.userbot_kb(cfg))
    elif arg == "info":
        await show(cb, T.info(cfg.bot_username, cfg.channel), K.info_kb())
    else:
        await cb.answer()


async def send_event(cb: CallbackQuery, bot: Bot, db: Database, owner: dict,
                     event_id: int) -> None:
    event = await db.get_event(owner["user_id"], event_id)
    if event is None:
        await cb.answer("Событие не найдено", show_alert=True)
        return
    msg = cb.message
    thread = msg.message_thread_id if isinstance(msg, Message) else None
    await deliver(bot, cb.from_user.id, event["html"], media_type=event["media_type"],
                  file_id=event["file_id"], thread_id=thread)
    await cb.answer()

