"""Все тексты и карточки событий (HTML). Не зависит от aiogram."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

CLIP = 1500  # максимум символов текста в одной цитате

MEDIA_LABELS = {
    "photo": "🖼 Фото",
    "video": "🎬 Видео",
    "animation": "🎞 GIF",
    "document": "📎 Файл",
    "voice": "🎤 Голосовое",
    "audio": "🎵 Аудио",
    "video_note": "⭕️ Кружок",
    "sticker": "🏷 Стикер",
}


# ---------------------------------------------------------------- хелперы
def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def clip(text: str, limit: int = CLIP) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def quote(text: str) -> str:
    """Цитата с моноширинным текстом (как на скриншотах)."""
    body = esc(clip(text)) or "—"
    return f"<blockquote><pre>{body}</pre></blockquote>"


def media_label(media_type: Optional[str]) -> str:
    return MEDIA_LABELS.get(media_type or "", "📎 Вложение")


def fmt_dt(tz: ZoneInfo, ts: int) -> str:
    d = datetime.fromtimestamp(ts, tz)
    return f"{d:%d.%m.%Y} в {d:%H:%M:%S} {d.strftime('%Z')}"


def fmt_short(tz: ZoneInfo, ts: int) -> str:
    return f"{datetime.fromtimestamp(ts, tz):%d.%m %H:%M}"


def fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f"{days} дн. {hours} ч. {minutes} мин."


def where(name: str, chat_id: int) -> str:
    return f"{esc(name)} (<code>{chat_id}</code>)"


def who(name: str, username: Optional[str], user_id: Optional[int]) -> str:
    uname = f" (@{esc(username)})" if username else ""
    uid = f" (<code>{user_id}</code>)" if user_id is not None else ""
    return f"{esc(name)}{uname}{uid}"


def header(when: str, where_: str, who_: str) -> str:
    return f"<b>Когда:</b> {when}\n<b>Где:</b> {where_}\n<b>Кто:</b> {who_}"


# ---------------------------------------------------------------- карточки
def card_edit(when: str, where_: str, who_: str, message_id: int, old: str, new: str) -> str:
    return (
        "✏️ <b>Сообщение изменено</b>\n\n"
        f"{header(when, where_, who_)}\n"
        f"<b>Сообщение ID:</b> {message_id}\n\n"
        f"<u><b>БЫЛО:</b></u>\n{quote(old)}\n\n"
        f"<u><b>СТАЛО:</b></u>\n{quote(new)}"
    )


def card_delete(when: str, where_: str, who_: str, text: str, media_type: Optional[str]) -> str:
    out = (
        "🗑 <b>Сообщение удалено</b>\n\n"
        f"{header(when, where_, who_)}\n\n"
        f"<b>Содержимое:</b>\n{quote(text)}"
    )
    if media_type:
        out += f"\n\n<b>Вложение:</b> {media_label(media_type)}"
    return out


def card_spy(when: str, where_: str, who_: str, media_type: str, caption: str) -> str:
    out = (
        "🕵️ <b>Одноразовое медиа сохранено</b>\n\n"
        f"{header(when, where_, who_)}\n"
        f"<b>Тип:</b> {media_label(media_type)}"
    )
    if caption:
        out += f"\n\n<b>Подпись:</b>\n{quote(caption)}"
    return out


# ---------------------------------------------------------------- меню
def connection_status(enabled: bool) -> str:
    if enabled:
        return "Бот-монитор успешно ✅ подключен к вашему бизнес-аккаунту."
    return "Бот-монитор успешно ❌ отключен от вашего бизнес-аккаунта."


def main_menu(first_name: Optional[str]) -> str:
    name = esc(first_name) if first_name else ":)"
    return (
        f"👋 <b>Главное меню, {name}</b>\n\n"
        "Выберите нужный раздел. Меню работает одинаково во всех Telegram-клиентах."
    )


def profile(deleted: int, edited: int, seconds: int) -> str:
    return (
        "👤 <b>Ваш профиль</b>\n\n"
        f"🗑 Удалено сообщений: <b>{deleted}</b>\n"
        f"✏️ Изменено сообщений: <b>{edited}</b>\n\n"
        f"🕒 С момента подключения прошло: <b>{fmt_duration(seconds)}</b>"
    )


NOTIFICATIONS = (
    "🔔 <b>Настройки уведомлений</b>\n\n"
    "Здесь вы можете выбрать, какие события будут приходить вам в личные сообщения.\n"
    "<i>Независимо от настроек, все события сохраняются в Истории.</i>\n\n"
    "🔹 <b>Свои действия</b> — уведомлять, если ВЫ сами удалили или изменили сообщение.\n"
    "🔹 <b>Изменения</b> — уведомлять, когда собеседник изменяет сообщение.\n"
    "🔹 <b>Удаления</b> — уведомлять, когда собеседник удаляет сообщение.\n"
    "🔹 <b>Боты</b> — разрешить уведомления об изменениях и удалениях в диалогах с ботами.\n\n"
    "<i>Сообщения с ботами сохраняются отдельно; переключатель влияет только на уведомления.</i>"
)

SPY = (
    "🕵️ <b>Spy — одноразовые медиа</b>\n\n"
    "Бот сохраняет фото, видео, кружки и голосовые с одноразовым просмотром.\n\n"
    "<b>Как сохранить:</b> в личном чате ответьте (reply) на одноразовое медиа любым "
    "сообщением — копия сразу придёт вам сюда.\n\n"
    "🔹 <b>Одноразки при ответе</b> — включает сохранение.\n"
    "🔹 <b>Любое медиа при ответе</b> — сохранять копию при ответе на любое медиа, "
    "даже если оно обычное.\n\n"
    "<i>Работает только в диалогах с пользователями.</i>"
)

SPY_HOWTO = (
    "❓ <b>Как сохранять самоуничтожающиеся медиа</b>\n\n"
    "1. Откройте личный чат, где пришло одноразовое фото, видео, кружок или голосовое.\n"
    "2. Не открывая его, нажмите на сообщение и выберите «Ответить».\n"
    "3. Отправьте любой ответ (хватит одной точки).\n"
    "4. Бот пришлёт вам копию в раздел «Изменённые».\n\n"
    "Раздел Spy → переключатель «Одноразки при ответе» должен быть включён."
)

USERBOT = (
    "🛠 <b>Меню Юзербота</b>\n\n"
    "Ваш бот оснащён системой плагинов, которые позволяют управлять аккаунтом через "
    "команды прямо в чате.\n\n"
    "<b>Доступные возможности:</b>\n"
    "🔹 Смена имени по времени\n"
    "🔹 Эффект печатной машинки\n"
    "🔹 Режим игнора (Mute)\n\n"
    "Полный список команд и инструкцию читайте ниже. Или через команду <code>.help</code>\n"
    "<b>Важно:</b> Юзербот работает только в диалоге с пользователями. "
    "В ботах, группах он работать не будет."
)

USERBOT_HELP = (
    "🛠 <b>Команды юзербота</b>\n\n"
    "Пишите их в личном чате от своего имени. После выполнения бот удалит команду.\n\n"
    "<code>.mute</code> — режим игнора в этом чате: новые сообщения собеседника сразу "
    "удаляются. Повторная команда выключает режим.\n"
    "<code>.type текст</code> — отправляет текст эффектом печатной машинки.\n"
    "<code>.clock</code> — имя аккаунта со временем (<i>Имя | 22:05</i>). "
    "Повторная команда возвращает обычное имя. <code>.clock Имя</code> — задать "
    "своё имя.\n"
    "<code>.help</code> — эта справка.\n\n"
    "<i>Нужны права бота в Telegram Business: управление сообщениями (для .mute и "
    ".type) и изменение имени (для .clock).</i>"
)

def info(bot_username: str, channel: str) -> str:
    out = (
        "ℹ️ <b>Инструкция по подключению и информация</b>\n\n"
        "Для подключения <b>Telegram Premium не требуется</b>. Выполните следующие шаги:\n\n"
        '1. Откройте <a href="tg://settings/edit">настройки профиля Telegram</a> '
        "(<code>tg://settings/edit</code>).\n"
        "2. Найдите блок <b>Автоматизация чатов</b>.\n"
        f"3. Укажите username бота: @{esc(bot_username)}.\n"
        "4. Разрешите боту читать все новые сообщения и управлять ими.\n\n"
        "После этого я начну отслеживать измененные и удаленные сообщения, а также "
        "сохранять медиафайлы."
    )
    if channel:
        out += f"\n\n<b>Канал проекта:</b> {esc(channel)}"
    return out


def history_title(page: int, pages: int) -> str:
    return f"🗃 <b>История событий (Стр. {page + 1}/{pages})</b>"


HISTORY_EMPTY = "🗃 <b>История событий</b>\n\nПока пусто: события появятся здесь, как только они произойдут."

NOT_CONNECTED = (
    "Сначала подключите бота: Настройки → Автоматизация чатов → укажите username бота."
)
