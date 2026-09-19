import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.game.manager import GameError, manager
from bot.keyboards import add_to_group_keyboard

router = Router(name="private")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(CommandStart(deep_link=True, magic=F.args.startswith("join_")))
async def start_join(message: Message, command: CommandObject) -> None:
    game_id = command.args.removeprefix("join_")
    try:
        game = await manager.join(game_id, message.from_user)
    except GameError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        f"✅ Вы в игре в чате «{html.escape(game.chat_title)}»!\n"
        f"Игроков: {len(game.players)}. Когда игра начнётся, я пришлю вашу роль сюда.\n\n"
        "Передумали? /leave"
    )


@router.message(CommandStart())
async def start_plain(message: Message) -> None:
    await message.answer(
        f"🎭 Привет, <b>{html.escape(message.from_user.first_name)}</b>! Я веду игру «Мафия» в группах.\n\n"
        "1. Добавь меня в группу и сделай админом (чтобы я мог удалять сообщения мёртвых).\n"
        "2. Напиши в группе /game.\n"
        "3. Игроки жмут «Присоединиться» — и поехали!\n\n"
        "/rules — правила · /roles — роли · /stats — твоя статистика",
        reply_markup=add_to_group_keyboard(),
    )


@router.message(Command("leave"))
async def private_leave(message: Message) -> None:
    try:
        game = await manager.leave(message.from_user.id)
        await message.answer(f"👋 Вы вышли из игры в чате «{html.escape(game.chat_title)}».")
    except GameError as exc:
        await message.answer(str(exc))


@router.message(F.text & ~F.text.startswith("/"))
async def private_text(message: Message) -> None:
    reply = await manager.private_text(message.from_user, message.text)
    if reply:
        await message.answer(reply)
