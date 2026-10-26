"""Inline-клавиатуры."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import texts as T
from .config import Config

PAGE_SIZE = 15
EVENT_ICONS = {"edit": "✏️", "delete": "🗑", "spy": "🖼"}


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _mark(value: object) -> str:
    return "✅" if value else "❌"


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn("👤 Профиль", "menu:profile"), _btn("🔔 Уведомления", "menu:notif"))
    b.row(_btn("🗃 История", "hist:0"), _btn("🕵️ Spy", "menu:spy"))
    b.row(_btn("🛠 Юзербот", "menu:userbot"))
    b.row(_btn("ℹ️ Инфо / Инструкция", "menu:info"))
    return b.as_markup()


def back_to_menu(text: str = "⬅️ Назад в главное меню") -> InlineKeyboardMarkup:
    return InlineKeyboardBuilder().row(_btn(text, "menu:main")).as_markup()


def profile_kb() -> InlineKeyboardMarkup:
    return back_to_menu("⬅️ Назад")


def notifications_kb(owner: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn(f"{_mark(owner['notif_self'])} Свои действия", "notif:self"))
    b.row(_btn(f"{_mark(owner['notif_edit'])} Изменения", "notif:edit"))
    b.row(_btn(f"{_mark(owner['notif_delete'])} Удаления", "notif:delete"))
    b.row(_btn(f"{_mark(owner['notif_bots'])} Боты", "notif:bots"))
    b.row(_btn("⬅️ Назад в главное меню", "menu:main"))
    return b.as_markup()


def spy_kb(owner: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn(f"{_mark(owner['spy_on'])} Одноразки при ответе", "spy:on"))
    b.row(_btn(f"{_mark(owner['spy_any'])} Любое медиа при ответе", "spy:any"))
    b.row(_btn("❓ Как сохранять самоуничтожающиеся медиа", "info:spy"))
    b.row(_btn("⬅️ Назад в главное меню", "menu:main"))
    return b.as_markup()


def userbot_kb(cfg: Config) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if cfg.instruction_url:
        b.row(InlineKeyboardButton(text="📖 Читать инструкцию", url=cfg.instruction_url))
    else:
        b.row(_btn("📖 Читать инструкцию", "ub:help"))
    b.row(_btn("⬅️ Назад в главное меню", "menu:main"))
    return b.as_markup()


def userbot_help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardBuilder().row(_btn("⬅️ Назад", "menu:userbot")).as_markup()


def info_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(_btn("❓ Как сохранять самоуничтожающиеся медиа", "info:spy"))
    b.row(_btn("⬅️ Назад в главное меню", "menu:main"))
    return b.as_markup()


def spy_howto_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardBuilder().row(_btn("⬅️ Назад", "menu:spy")).as_markup()


def history_kb(events: list[dict], page: int, pages: int, tz: ZoneInfo) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ev in events:
        icon = EVENT_ICONS.get(ev["kind"], "•")
        label = T.clip(ev["label"], 28)
        b.row(_btn(f"{icon} {label} - {T.fmt_short(tz, ev['ts'])}", f"ev:{ev['id']}"))
    nav = []
    if page > 0:
        nav.append(_btn("◀️", f"hist:{page - 1}"))
    nav.append(_btn("🔄", f"hist:{page}"))
    if page < pages - 1:
        nav.append(_btn("▶️", f"hist:{page + 1}"))
    b.row(*nav)
    b.row(_btn("⬅️ Назад в меню", "menu:main"))
    return b.as_markup()
