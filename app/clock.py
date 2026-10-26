"""Фоновые задачи: имя по времени и очистка старых копий сообщений."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from .config import Config
from .db import Database
from .services import deliver

log = logging.getLogger(__name__)


async def clock_loop(bot: Bot, db: Database, cfg: Config) -> None:
    """Раз в минуту обновляет имя аккаунта вида «Имя | 22:05» у тех, кто включил .clock."""
    while True:
        try:
            now = datetime.now(cfg.tz)
            stamp = now.strftime("%H:%M")
            for owner in await db.clock_owners():
                if owner["clock_last"] == stamp:
                    continue
                name = f"{owner['clock_base'] or owner['first_name'] or ''} | {stamp}"[:64]
                try:
                    await bot.set_business_account_name(
                        business_connection_id=owner["connection_id"],
                        first_name=name, last_name=owner["last_name"])
                    await db.set_clock_last(owner["user_id"], stamp)
                except TelegramRetryAfter as exc:
                    log.warning("Лимит на смену имени, жду %s с", exc.retry_after)
                    await asyncio.sleep(exc.retry_after + 1)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Смена имени не удалась: %s", exc)
                    await db.set_flag(owner["user_id"], "clock_on", False)
                    await deliver(
                        bot, owner["chat_id"],
                        "⚠️ Не удалось сменить имя, режим «имя по времени» выключен. "
                        "Проверьте, что у бота есть право на изменение имени аккаунта.",
                        thread_id=owner["topic_menu"] or None)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле имени по времени")
        await asyncio.sleep(max(1.0, 60.5 - datetime.now(cfg.tz).second))


async def cleanup_loop(db: Database, cfg: Config) -> None:
    """Удаляет копии сообщений старше RETAIN_DAYS. События в истории остаются."""
    while True:
        try:
            await db.cleanup(int(time.time()) - cfg.retain_days * 86400)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка очистки старых сообщений")
        await asyncio.sleep(6 * 3600)
