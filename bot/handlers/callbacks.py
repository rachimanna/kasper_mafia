import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.game.manager import GameError, manager

logger = logging.getLogger(__name__)
router = Router(name="callbacks")


def _parse(data: str, expected_parts: int):
    parts = data.split(":")
    if len(parts) != expected_parts:
        raise GameError("Кнопка устарела.")
    return parts


async def _run(callback: CallbackQuery, coro) -> None:
    try:
        answer = await coro
        await callback.answer(answer or None)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
    except Exception:
        logger.exception("Callback %s failed", callback.data)
        await callback.answer("Что-то пошло не так 😕", show_alert=True)


@router.callback_query(F.data.startswith("n:"))
async def night_action(callback: CallbackQuery) -> None:
    async def go():
        _, game_id, round_, action, target = _parse(callback.data, 5)
        if not isinstance(callback.message, Message):
            raise GameError("Сообщение устарело.")
        return await manager.night_action(game_id, int(round_), callback.from_user.id, action, int(target), callback.message)
    await _run(callback, go())


@router.callback_query(F.data.startswith("cm:"))
async def commissar_mode(callback: CallbackQuery) -> None:
    async def go():
        _, game_id, round_, mode = _parse(callback.data, 4)
        if not isinstance(callback.message, Message):
            raise GameError("Сообщение устарело.")
        return await manager.commissar_mode(game_id, int(round_), callback.from_user.id, mode, callback.message)
    await _run(callback, go())


@router.callback_query(F.data.startswith("v:"))
async def day_vote(callback: CallbackQuery) -> None:
    async def go():
        _, game_id, round_, target = _parse(callback.data, 4)
        if not isinstance(callback.message, Message):
            raise GameError("Сообщение устарело.")
        return await manager.day_vote(game_id, int(round_), callback.from_user.id, int(target), callback.message)
    await _run(callback, go())


@router.callback_query(F.data.startswith("c:"))
async def confirm(callback: CallbackQuery) -> None:
    async def go():
        _, game_id, round_, choice = _parse(callback.data, 4)
        return await manager.confirm_vote(game_id, int(round_), callback.from_user.id, choice == "y")
    await _run(callback, go())
