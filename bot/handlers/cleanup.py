"""Мёртвые молчат, ночью молчат все игроки: удаляем такие сообщения в группе (нужны права админа)."""
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from bot.config import config
from bot.game.manager import manager

router = Router(name="cleanup")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


@router.message()
async def cleanup(message: Message, bot: Bot) -> None:
    if not config.DELETE_MESSAGES or message.from_user is None:
        return
    if manager.should_delete(message.chat.id, message.from_user.id):
        try:
            await message.delete()
        except TelegramAPIError:
            pass
