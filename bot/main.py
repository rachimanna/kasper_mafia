import asyncio
import logging
import sys
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from aiohttp import web

from bot.config import config
from bot.db import db
from bot.game.manager import manager
from bot.handlers import callbacks, cleanup, group, info, private

logger = logging.getLogger("bot")


async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text=f"kasper_mafia is running, games: {len(manager.by_chat)}")


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logger.info("Health server started on port %s", config.PORT)
    return runner


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # Порядок важен: команды раньше «уборщика» сообщений.
    dp.include_routers(info.router, group.router, private.router, callbacks.router, cleanup.router)
    return dp


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="game", description="Начать набор в игру"),
            BotCommand(command="begin", description="Начать досрочно"),
            BotCommand(command="extend", description="Продлить набор"),
            BotCommand(command="leave", description="Выйти из игры"),
            BotCommand(command="stop", description="Остановить игру"),
            BotCommand(command="top", description="Топ игроков чата"),
            BotCommand(command="rules", description="Правила"),
            BotCommand(command="roles", description="Роли"),
        ],
        scope=BotCommandScopeAllGroupChats(),
    )
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начало"),
            BotCommand(command="stats", description="Моя статистика"),
            BotCommand(command="rules", description="Правила"),
            BotCommand(command="roles", description="Роли"),
            BotCommand(command="leave", description="Выйти из текущей игры"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )


def create_bot() -> Bot:
    session = AiohttpSession(api=TelegramAPIServer.from_base(config.API_SERVER)) if config.API_SERVER else None
    return Bot(token=config.BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    runner: Optional[web.AppRunner] = None
    bot = create_bot()
    try:
        if config.WEB_SERVER_ENABLED:
            runner = await start_web_server()
        await db.init()
        me = await bot.get_me()
        config.BOT_USERNAME = me.username or ""
        logger.info("Authorized as @%s", config.BOT_USERNAME)
        manager.setup(bot)
        try:
            await set_commands(bot)
        except Exception as exc:  # не критично
            logger.warning("Cannot set commands: %s", exc)

        dp = build_dispatcher()
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Bot is ready")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for game in list(manager.by_chat.values()):
            if game.task:
                game.task.cancel()
        await db.close()
        if runner:
            await runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
