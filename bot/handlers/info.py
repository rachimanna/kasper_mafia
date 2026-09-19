import html

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from bot import texts
from bot.db import db
from bot.game.roles import ROLES, TEAM_TITLES, Role, Team

router = Router(name="info")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🎭 <b>Команды</b>\n\n"
        "<b>В группе:</b>\n"
        "/game — начать набор\n/begin — начать досрочно\n/extend — продлить набор\n"
        "/stop — остановить игру\n/leave — выйти из игры\n/top — топ игроков чата\n\n"
        "<b>Везде:</b>\n/rules — правила\n/roles — роли\n/stats — твоя статистика"
    )


@router.message(Command("rules"))
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.RULES)


@router.message(Command("roles"))
async def cmd_roles(message: Message) -> None:
    blocks = []
    for team in (Team.TOWN, Team.MAFIA, Team.MANIAC, Team.JESTER):
        roles = [info for info in ROLES.values() if info.team == team]
        lines = "\n".join(f"<b>{info.title}</b> — {info.description}" for info in roles)
        blocks.append(f"{TEAM_TITLES[team]}\n{lines}")
    await message.answer("🎭 <b>Роли</b>\n\n" + "\n\n".join(blocks))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    games, wins, survived, roles = await db.user_stats(message.from_user.id)
    name = html.escape(message.from_user.full_name)
    if not games:
        await message.answer(f"📊 {name}, вы ещё не сыграли ни одной игры. Начните: /game в группе.")
        return
    role_lines = "\n".join(
        f"{ROLES[Role(r)].title}: {c} игр, {w} побед" for r, c, w in roles if r in Role._value2member_map_
    )
    await message.answer(
        f"📊 <b>Статистика {name}</b>\n\n"
        f"🎮 Игр: {games}\n🏆 Побед: {wins} ({wins * 100 // games}%)\n❤️ Выжил(а): {survived}\n\n{role_lines}"
    )


@router.message(Command("top"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def cmd_top(message: Message) -> None:
    rows = await db.top(message.chat.id)
    if not rows:
        await message.answer("🏆 В этом чате ещё не было игр. Начните: /game")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i] if i < 3 else f'{i + 1}.'} {html.escape(name)} — {wins} побед из {games}"
        for i, (name, wins, games) in enumerate(rows)
    ]
    await message.answer("🏆 <b>Топ игроков чата</b>\n\n" + "\n".join(lines))
