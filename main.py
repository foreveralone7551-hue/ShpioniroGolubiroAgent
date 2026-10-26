"""Точка входа: python main.py"""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiohttp import ClientSession, ClientTimeout, web
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.clock import cleanup_loop, clock_loop
from app.config import load_config
from app.db import Database
from app.handlers import business, private


async def start_health_server() -> None:
    """Render (Web Service) требует открытый порт. Отдаём «ok» на любой GET /."""
    port = os.getenv("PORT")
    if not port:
        return
    app = web.Application()
    app.router.add_get("/", lambda _request: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    logging.info("Health-сервер на порту %s", port)


async def keep_alive_loop() -> None:
    """Бесплатный Render усыпляет сервис без входящих запросов: пингуем свой адрес."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        await asyncio.sleep(600)
        try:
            async with ClientSession(timeout=ClientTimeout(total=20)) as session:
                await session.get(url)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Самопинг не удался: %s", exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    db = Database(cfg.db_path)

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(db=db, cfg=cfg)
    # business раньше private: у business_message свой тип обновления, конфликтов нет
    dp.include_router(business.router)
    dp.include_router(private.router)

    await start_health_server()
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
    me = await bot.get_me()
    logging.info("Запущен @%s", me.username)

    background = [
        asyncio.create_task(clock_loop(bot, db, cfg)),
        asyncio.create_task(cleanup_loop(db, cfg)),
        asyncio.create_task(keep_alive_loop()),
    ]
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background:
            task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
