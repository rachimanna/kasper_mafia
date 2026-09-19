from typing import Dict, Iterable, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.game.models import SKIP, Player


def bot_link(payload: Optional[str] = None) -> str:
    url = f"https://t.me/{config.BOT_USERNAME}"
    return f"{url}?start={payload}" if payload else url


def lobby_keyboard(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋 Присоединиться", url=bot_link(f"join_{game_id}"))],
    ])


def go_to_bot_keyboard(text: str = "🤖 Перейти к боту") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=bot_link())]])


def add_to_group_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="➕ Добавить в группу", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true")
    ]])


def targets_keyboard(prefix: str, targets: Iterable[Player], skip_text: Optional[str] = "⏭ Пропустить") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in targets:
        builder.button(text=p.label, callback_data=f"{prefix}:{p.user_id}")
    builder.adjust(2)
    if skip_text:
        builder.row(InlineKeyboardButton(text=skip_text, callback_data=f"{prefix}:{SKIP}"))
    return builder.as_markup()


def commissar_mode_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Проверить", callback_data=f"{prefix}:check"),
            InlineKeyboardButton(text="🔫 Стрелять", callback_data=f"{prefix}:shoot"),
        ],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"{prefix}:skip")],
    ])


def confirm_keyboard(prefix: str, yes: int, no: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"👍 Вешать ({yes})", callback_data=f"{prefix}:y"),
        InlineKeyboardButton(text=f"👎 Помиловать ({no})", callback_data=f"{prefix}:n"),
    ]])
