import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import config
from bot.game.manager import GameError, manager
from bot.keyboards import go_to_bot_keyboard

logger = logging.getLogger(__name__)

router = Router(name="group")
router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as exc:  # сеть, права, неожиданный ответ API
        logger.warning("Cannot check admin rights: %s", exc)
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


@router.message(Command("game"))
async def cmd_game(message: Message) -> None:
    try:
        await manager.create_game(message.chat.id, message.chat.title or "", message.from_user)
    except GameError as exc:
        await message.reply(str(exc))


@router.message(Command("begin"))
async def cmd_begin(message: Message, bot: Bot) -> None:
    game = manager.by_chat.get(message.chat.id)
    if game is None:
        await message.reply("Сейчас нет набора в игру. Начать: /game")
        return
    if message.from_user.id != game.creator_id and not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Начать досрочно может только тот, кто создал игру, или админ.")
        return
    try:
        await manager.begin(game)
    except GameError as exc:
        await message.reply(str(exc))


@router.message(Command("extend"))
async def cmd_extend(message: Message) -> None:
    game = manager.by_chat.get(message.chat.id)
    if game is None:
        await message.reply("Сейчас нет набора в игру. Начать: /game")
        return
    try:
        await manager.extend(game)
        await message.reply(f"⏳ Набор продлён на {config.REGISTRATION_EXTEND} сек.")
    except GameError as exc:
        await message.reply(str(exc))


@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot) -> None:
    game = manager.by_chat.get(message.chat.id)
    if game is None:
        await message.reply("Сейчас игра не идёт.")
        return
    if message.from_user.id != game.creator_id and not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Остановить игру может только её создатель или админ.")
        return
    await manager.stop(game, f"🛑 {message.from_user.full_name} остановил(а) игру.")


@router.message(Command("leave"))
async def cmd_leave(message: Message) -> None:
    try:
        await manager.leave(message.from_user.id)
    except GameError as exc:
        await message.reply(str(exc))


@router.message(Command("start"))
async def cmd_start_group(message: Message) -> None:
    await message.reply(
        "🎭 Я веду игру «Мафия».\n/game — начать набор · /rules — правила · /roles — роли\n\n"
        "Чтобы играть, каждому нужно хотя бы раз написать мне в личку.",
        reply_markup=go_to_bot_keyboard(),
    )
