"""Жизненный цикл игр: лобби → ночь → день → голосование → … → итоги."""
import asyncio
import html
import logging
import random
import time
import uuid
from typing import Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, Message, User

from bot import texts
from bot.config import config
from bot.db import db
from bot.game.models import SKIP, Game, Phase, Player
from bot.game.roles import (
    ACTION_COMMISSAR, ACTION_DON_CHECK, ACTION_HEAL, ACTION_KILL, ACTION_LOVE,
    MAFIA_TEAM, ROLES, TEAM_TITLES, Role, role_title,
)
from bot.game.rules import (
    actions_for, allowed_targets, assign_roles, check_winner, is_winner, night_complete,
    resolve_night, tally_day_votes, Outcome,
)
from bot.keyboards import (
    commissar_mode_keyboard, confirm_keyboard, go_to_bot_keyboard, lobby_keyboard, targets_keyboard,
)

logger = logging.getLogger(__name__)

ACTION_PROMPTS = {
    ACTION_KILL: "🔪 Кого мафия убьёт этой ночью?",
    ACTION_DON_CHECK: "🎩 Кого проверить — не комиссар ли он?",
    ACTION_COMMISSAR: "🕵️ Кого?",
    ACTION_HEAL: "🩺 Кого лечить этой ночью?",
    ACTION_LOVE: "💃 К кому пойти в гости?",
    "lawyer": "💼 Кого взять под защиту от проверки комиссара?",
    "maniac": "🪓 Кого убить этой ночью?",
    "hobo": "🧥 К чьему дому пойти за бутылками?",
}


def _prompt(message: Message) -> str:
    """Текст вопроса из сообщения с кнопками (чтобы после выбора было видно, к чему он относился)."""
    try:
        return message.html_text or ""
    except Exception:
        return html.escape(message.text or "")


class GameError(Exception):
    """Ошибка, которую нужно показать пользователю."""


class GameManager:
    def __init__(self) -> None:
        self.bot: Optional[Bot] = None
        self.by_chat: Dict[int, Game] = {}
        self.by_id: Dict[str, Game] = {}
        self.by_user: Dict[int, Game] = {}
        self.rng = random.Random()

    def setup(self, bot: Bot) -> None:
        self.bot = bot

    # ================================================================ отправка сообщений

    async def send(self, chat_id: int, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> Optional[Message]:
        for attempt in range(3):
            try:
                return await self.bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 0.5)
            except TelegramForbiddenError:
                logger.info("Cannot message %s: bot is blocked or chat unavailable", chat_id)
                return None
            except TelegramAPIError as exc:
                logger.warning("send_message to %s failed: %s", chat_id, exc)
                return None
        return None

    async def edit(self, chat_id: int, message_id: int, text: Optional[str] = None,
                   markup: Optional[InlineKeyboardMarkup] = None) -> None:
        try:
            if text is None:
                await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=markup)
            else:
                await self.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=message_id, reply_markup=markup, disable_web_page_preview=True
                )
        except TelegramRetryAfter:
            pass  # финальное состояние всё равно выставится позже
        except TelegramAPIError as exc:
            if "not modified" not in str(exc):
                logger.debug("edit failed: %s", exc)

    async def pause(self, seconds: Optional[float] = None) -> None:
        await asyncio.sleep(config.PHASE_PAUSE if seconds is None else seconds)

    # ================================================================ лобби

    def game_for_user(self, user_id: int) -> Optional[Game]:
        return self.by_user.get(user_id)

    async def create_game(self, chat_id: int, chat_title: str, creator: User) -> Game:
        if chat_id in self.by_chat:
            raise GameError("В этом чате уже идёт игра.")
        game = Game(id=uuid.uuid4().hex[:8], chat_id=chat_id, chat_title=chat_title or "чат", creator_id=creator.id)
        game.registration_deadline = time.monotonic() + config.REGISTRATION_TIME
        self.by_chat[chat_id] = game
        self.by_id[game.id] = game

        msg = await self.send(chat_id, self._lobby_text(game), lobby_keyboard(game.id))
        game.lobby_message_id = msg.message_id if msg else None
        game.task = asyncio.create_task(self._lifecycle(game), name=f"game-{game.id}")
        return game

    def _lobby_text(self, game: Game) -> str:
        players = list(game.players.values())
        lines = "\n".join(f"{i}. {p.mention}" for i, p in enumerate(players, start=1)) or "<i>пока никого</i>"
        left = max(0, int(game.registration_deadline - time.monotonic()))
        return (
            "🎲 <b>Набор в игру «Мафия»!</b>\n\n"
            f"👥 Игроки ({len(players)}/{config.MAX_PLAYERS}):\n{lines}\n\n"
            f"⏳ Старт примерно через {left // 60}:{left % 60:02d} · минимум {config.MIN_PLAYERS} игрока\n"
            "Нажми «Присоединиться» — откроется бот, и ты в игре.\n"
            "/extend — продлить набор, /begin — начать сразу"
        )

    async def _refresh_lobby(self, game: Game) -> None:
        if game.lobby_message_id and game.phase == Phase.LOBBY:
            await self.edit(game.chat_id, game.lobby_message_id, self._lobby_text(game), lobby_keyboard(game.id))

    async def join(self, game_id: str, user: User) -> Game:
        game = self.by_id.get(game_id)
        if game is None or game.phase == Phase.FINISHED:
            raise GameError("Эта игра уже закончилась. Попросите начать новую: /game")
        if game.phase != Phase.LOBBY:
            raise GameError("Игра уже началась — дождитесь следующей.")
        existing = self.by_user.get(user.id)
        if existing is game:
            raise GameError("Вы уже в этой игре 👍")
        if existing is not None:
            raise GameError(f"Вы уже участвуете в игре в чате «{html.escape(existing.chat_title)}».")
        if len(game.players) >= config.MAX_PLAYERS:
            raise GameError("Мест больше нет 😔")

        game.players[user.id] = Player(user_id=user.id, name=user.full_name or user.first_name or "Игрок")
        self.by_user[user.id] = game
        await self._refresh_lobby(game)
        if len(game.players) >= config.MAX_PLAYERS:
            game.start_now.set()
        return game

    async def extend(self, game: Game) -> None:
        if game.phase != Phase.LOBBY:
            raise GameError("Игра уже идёт.")
        game.registration_deadline += config.REGISTRATION_EXTEND
        await self._refresh_lobby(game)

    async def begin(self, game: Game) -> None:
        if game.phase != Phase.LOBBY:
            raise GameError("Игра уже идёт.")
        if len(game.players) < config.MIN_PLAYERS:
            raise GameError(f"Нужно минимум {config.MIN_PLAYERS} игрока, сейчас {len(game.players)}.")
        game.start_now.set()

    async def stop(self, game: Game, reason: str = "🛑 Игра остановлена.") -> None:
        if game.task and not game.task.done():
            game.task.cancel()
        await self.send(game.chat_id, reason)
        self._cleanup(game)

    async def leave(self, user_id: int) -> Game:
        game = self.by_user.get(user_id)
        if game is None:
            raise GameError("Вы не участвуете в игре.")
        player = game.players[user_id]
        if game.phase == Phase.LOBBY:
            del game.players[user_id]
            self.by_user.pop(user_id, None)
            await self._refresh_lobby(game)
            return game
        if not player.alive:
            raise GameError("Вы уже выбыли из игры.")
        await self._kill(game, player)
        await self.send(game.chat_id, f"🏃 {player.mention} сбежал(а) из города.{self._role_suffix(player)}")
        self._check_phase_done(game)
        return game

    def _cleanup(self, game: Game) -> None:
        game.phase = Phase.FINISHED
        if self.by_chat.get(game.chat_id) is game:
            del self.by_chat[game.chat_id]
        self.by_id.pop(game.id, None)
        for uid in list(game.players):
            if self.by_user.get(uid) is game:
                del self.by_user[uid]

    # ================================================================ основной цикл

    async def _lifecycle(self, game: Game) -> None:
        try:
            if not await self._registration(game):
                return
            await self._start(game)
            outcome: Optional[Outcome] = None
            while outcome is None:
                deaths_before = sum(not p.alive for p in game.players.values())
                await self._night(game)
                outcome = check_winner(game)
                if outcome:
                    break
                await self._day(game)
                outcome = check_winner(game)
                if outcome:
                    break
                deaths_after = sum(not p.alive for p in game.players.values())
                game.idle_rounds = game.idle_rounds + 1 if deaths_after == deaths_before else 0
                if game.idle_rounds >= config.MAX_IDLE_ROUNDS:
                    outcome = Outcome(None, f"🤝 Ничья — {config.MAX_IDLE_ROUNDS} круга подряд никто не погиб.")
            await self._finish(game, outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Game %s crashed", game.id)
            await self.send(game.chat_id, "💥 Игра прервалась из-за ошибки. Начните новую: /game")
        finally:
            self._cleanup(game)

    async def _registration(self, game: Game) -> bool:
        reminders = {60, 30, 10}
        while True:
            left = game.registration_deadline - time.monotonic()
            if left <= 0 or game.start_now.is_set():
                break
            next_mark = max([r for r in reminders if r < left], default=0)
            try:
                await asyncio.wait_for(game.start_now.wait(), timeout=left - next_mark)
                break
            except asyncio.TimeoutError:
                left = game.registration_deadline - time.monotonic()
                if next_mark and abs(left - next_mark) < 1.5 and game.phase == Phase.LOBBY:
                    reminders.discard(next_mark)
                    await self.send(
                        game.chat_id,
                        f"⏳ До начала игры {next_mark} сек. Игроков: {len(game.players)}",
                        lobby_keyboard(game.id),
                    )

        if len(game.players) < config.MIN_PLAYERS:
            if game.lobby_message_id:
                await self.edit(game.chat_id, game.lobby_message_id, "🎲 Набор в игру закрыт.")
            await self.send(
                game.chat_id,
                f"😔 Недостаточно игроков ({len(game.players)} из {config.MIN_PLAYERS}). Игра отменена.",
            )
            return False
        return True

    async def _start(self, game: Game) -> None:
        players = list(game.players.values())
        self.rng.shuffle(players)
        for number, p in enumerate(players, start=1):
            p.number = number
        game.players = {p.user_id: p for p in players}
        assign_roles(players, self.rng)
        game.phase = Phase.NIGHT  # закрываем лобби

        if game.lobby_message_id:
            await self.edit(game.chat_id, game.lobby_message_id, "🎲 Набор в игру закрыт.")

        counts: Dict[Role, int] = {}
        for p in players:
            counts[p.role] = counts.get(p.role, 0) + 1
        composition = ", ".join(
            f"{role_title(r)}{f' ×{c}' if c > 1 else ''}" for r, c in sorted(counts.items(), key=lambda x: list(Role).index(x[0]))
        )
        await self.send(
            game.chat_id,
            f"🎬 <b>Игра началась!</b> Игроков: {len(players)}\n\n"
            f"В городе: {composition}\n\n"
            "Роли отправлены в личку. Не показывайте их никому! 🤫",
            go_to_bot_keyboard("🤖 Узнать свою роль"),
        )

        mafia = game.mafia()
        for p in players:
            info = ROLES[p.role]
            text = f"🎭 Ваша роль: <b>{info.title}</b>\n\n{info.description}\n\nИгра в чате «{html.escape(game.chat_title)}»."
            if p.is_mafia:
                family = "\n".join(f"• {m.mention} — {role_title(m.role)}" for m in mafia)
                text += f"\n\n🤵 <b>Ваша семья:</b>\n{family}\n\nНочью всё, что вы пишете мне, увидят сообщники."
            if p.role == Role.SERGEANT:
                com = game.by_role(Role.COMMISSAR)
                if com:
                    text += f"\n\n🕵️ Ваш комиссар: {com[0].mention}"
            if p.role == Role.COMMISSAR:
                serg = game.by_role(Role.SERGEANT)
                if serg:
                    text += f"\n\n👮 Ваш сержант: {serg[0].mention}"
            await self.send(p.user_id, text)
        await self.pause()

    # ================================================================ ночь

    async def _night(self, game: Game) -> None:
        game.round += 1
        game.phase = Phase.NIGHT
        game.night = type(game.night)()
        game.prompts = []
        game.phase_done = asyncio.Event()

        await self.send(game.chat_id, texts.pick(texts.NIGHT_START, round=game.round) + "\n\nВсе, у кого есть ночной ход, — в личку к боту.",
                        go_to_bot_keyboard())

        for p in game.alive():
            await self._send_night_prompts(game, p)

        if not night_complete(game):
            try:
                await asyncio.wait_for(game.phase_done.wait(), timeout=config.NIGHT_TIME)
            except asyncio.TimeoutError:
                pass

        game.phase = Phase.RESOLVING
        for chat_id, message_id in game.prompts:
            await self.edit(chat_id, message_id, markup=None)

        result = resolve_night(game, self.rng)

        # Память для правил следующей ночи
        doctor = game.by_role(Role.DOCTOR)
        if doctor:
            heal = game.night.choice(doctor[0].user_id, ACTION_HEAL)
            game.doctor_last = heal if heal not in (None, SKIP) and doctor[0].user_id not in result.blocked else None
            if game.doctor_last == doctor[0].user_id:
                game.doctor_self_used = True
        lover = game.by_role(Role.LOVER)
        if lover:
            love = game.night.choice(lover[0].user_id, ACTION_LOVE)
            game.lover_last = love if love not in (None, SKIP) else None

        for uid, messages in result.private.items():
            player = game.players.get(uid)
            if player and (player.alive or uid in result.deaths):
                await self.send(uid, "\n".join(messages))

        await self.pause()
        lines = [texts.pick(texts.MORNING, round=game.round), ""]
        if result.deaths:
            for uid in result.deaths:
                p = game.players[uid]
                lines.append("💀 " + texts.pick(texts.DEATH, mention=p.mention) + self._role_suffix(p))
        else:
            lines.append(texts.pick(texts.NO_DEATHS))
        if result.saved:
            lines.append(texts.SAVED)

        dead_players = [game.players[uid] for uid in result.deaths]
        for p in dead_players:
            await self._kill(game, p)
        await self.send(game.chat_id, "\n".join(lines))

        for p in dead_players:
            await self._offer_last_words(game, p, "💀 Вас убили этой ночью.")

    async def _send_night_prompts(self, game: Game, p: Player) -> None:
        actions = actions_for(p)
        if not actions:
            if p.role == Role.SERGEANT:
                await self.send(p.user_id, f"🌃 Ночь {game.round}. Ждите вестей от комиссара…")
            else:
                await self.send(p.user_id, f"🌃 Ночь {game.round}. Вы крепко спите… 😴")
            return
        for action in actions:
            prefix = f"n:{game.id}:{game.round}:{action}"
            if action == ACTION_COMMISSAR:
                msg = await self.send(p.user_id, f"🌃 Ночь {game.round}. Что делаем, комиссар?",
                                      commissar_mode_keyboard(f"cm:{game.id}:{game.round}"))
            else:
                targets = allowed_targets(game, p, action)
                hint = ""
                if action == ACTION_HEAL and game.doctor_self_used:
                    hint = "\n<i>Себя вы уже лечили.</i>"
                msg = await self.send(p.user_id, f"🌃 Ночь {game.round}. {ACTION_PROMPTS[action]}{hint}",
                                      targets_keyboard(prefix, targets))
            if msg:
                game.prompts.append((p.user_id, msg.message_id))

    async def commissar_mode(self, game_id: str, round_: int, user_id: int, mode: str, message: Message) -> str:
        game, player = self._night_actor(game_id, round_, user_id, ACTION_COMMISSAR)
        if game.night.choice(user_id, ACTION_COMMISSAR) is not None:
            return "Вы уже сделали ход."
        if mode == "skip":
            game.night.choices[(user_id, ACTION_COMMISSAR)] = SKIP
            await self.edit(user_id, message.message_id, f"{_prompt(message)}\n\n⏭ Вы решили отдохнуть этой ночью.")
            self._check_phase_done(game)
            return "Пропуск"
        game.night.commissar_mode = "shoot" if mode == "shoot" else "check"
        verb = "🔫 В кого стрелять?" if mode == "shoot" else "🔍 Кого проверить?"
        targets = allowed_targets(game, player, ACTION_COMMISSAR)
        await self.edit(user_id, message.message_id, f"🌃 Ночь {game.round}. {verb}",
                        targets_keyboard(f"n:{game.id}:{game.round}:{ACTION_COMMISSAR}", targets))
        return ""

    def _night_actor(self, game_id: str, round_: int, user_id: int, action: str):
        game = self.by_id.get(game_id)
        if game is None or game.phase == Phase.FINISHED:
            raise GameError("Эта игра уже закончилась.")
        if game.phase != Phase.NIGHT or game.round != round_:
            raise GameError("Эта ночь уже прошла.")
        player = game.players.get(user_id)
        if player is None or not player.alive:
            raise GameError("Вы не можете ходить.")
        if action not in actions_for(player):
            raise GameError("Это действие вам недоступно.")
        return game, player

    async def night_action(self, game_id: str, round_: int, user_id: int, action: str, target: int, message: Message) -> str:
        game, player = self._night_actor(game_id, round_, user_id, action)
        if game.night.choice(user_id, action) is not None:
            return "Вы уже сделали ход."
        if action == ACTION_COMMISSAR and game.night.commissar_mode is None:
            return "Сначала выберите: проверить или стрелять."

        if target != SKIP:
            allowed = {p.user_id for p in allowed_targets(game, player, action)}
            if target not in allowed:
                return "Эту цель выбрать нельзя."
        game.night.choices[(user_id, action)] = target

        if target == SKIP:
            await self.edit(user_id, message.message_id, f"{_prompt(message)}\n\n⏭ Вы пропустили ход.")
        else:
            target_player = game.players[target]
            await self.edit(user_id, message.message_id, f"{_prompt(message)}\n\n✅ Ваш выбор: {target_player.mention}")
            if action == ACTION_KILL:
                for m in game.mafia():
                    if m.user_id != user_id:
                        await self.send(m.user_id, f"🔪 {player.mention} голосует за {target_player.mention}")
            if action not in game.night.announced:
                game.night.announced.add(action)
                await self.send(game.chat_id, texts.ACTION_FLAVOR[action])

        self._check_phase_done(game)
        return "Принято"

    # ================================================================ день

    async def _day(self, game: Game) -> None:
        game.phase = Phase.DAY
        alive = game.alive()
        discussion = config.DAY_TIME + config.DAY_TIME_PER_PLAYER * len(alive)
        roster = "\n".join(f"{p.number}. {p.mention}" for p in alive)
        await self.send(
            game.chat_id,
            f"🗣 <b>День {game.round}.</b> Время обсудить, кто мафия!\n\n"
            f"Живые ({len(alive)}):\n{roster}\n\n⏳ Голосование через {discussion} сек.",
        )
        await asyncio.sleep(discussion)
        if check_winner(game):
            return

        # --- голосование в личке ---
        game.phase = Phase.VOTE
        game.votes = {}
        game.phase_done = asyncio.Event()
        game.prompts = []
        vote_msg = await self.send(
            game.chat_id, self._vote_text(game), go_to_bot_keyboard("🗳 Голосовать")
        )
        game.vote_message_id = vote_msg.message_id if vote_msg else None
        for p in game.alive():
            targets = [t for t in game.alive() if t.user_id != p.user_id]
            msg = await self.send(
                p.user_id, f"🗳 День {game.round}. Кого казнить?",
                targets_keyboard(f"v:{game.id}:{game.round}", targets, skip_text="🤷 Воздержаться"),
            )
            if msg:
                game.prompts.append((p.user_id, msg.message_id))
        try:
            await asyncio.wait_for(game.phase_done.wait(), timeout=config.VOTE_TIME)
        except asyncio.TimeoutError:
            pass
        game.phase = Phase.RESOLVING
        for chat_id, message_id in game.prompts:
            await self.edit(chat_id, message_id, markup=None)
        if game.vote_message_id:
            await self.edit(game.chat_id, game.vote_message_id, self._vote_text(game, final=True))

        await self._punish_afk(game)
        alive_ids = set(game.alive_ids())
        candidate_id = tally_day_votes({v: t for v, t in game.votes.items() if v in alive_ids and (t == SKIP or t in alive_ids)})
        if candidate_id is None:
            await self.send(game.chat_id, "🤷 Город не смог договориться. Сегодня никого не казнят.")
            await self.pause()
            return

        # --- подтверждение в чате ---
        candidate = game.players[candidate_id]
        game.candidate = candidate_id
        game.confirm = {}
        game.phase = Phase.CONFIRM
        game.phase_done = asyncio.Event()
        msg = await self.send(
            game.chat_id,
            f"⚖️ Город выбрал {candidate.mention}. Вешаем?\n<i>Голосуют все живые, кроме обвиняемого. {config.CONFIRM_TIME} сек.</i>",
            confirm_keyboard(f"c:{game.id}:{game.round}", 0, 0),
        )
        game.confirm_message_id = msg.message_id if msg else None
        try:
            await asyncio.wait_for(game.phase_done.wait(), timeout=config.CONFIRM_TIME)
        except asyncio.TimeoutError:
            pass
        game.phase = Phase.RESOLVING
        yes = sum(1 for uid, v in game.confirm.items() if v and game.players[uid].alive)
        no = sum(1 for uid, v in game.confirm.items() if not v and game.players[uid].alive)
        if game.confirm_message_id:
            await self.edit(game.chat_id, game.confirm_message_id,
                            f"⚖️ Суд над {candidate.mention}: 👍 {yes} · 👎 {no}")

        if not candidate.alive:
            return
        if yes <= no:
            await self.send(game.chat_id, f"🙏 Город помиловал {candidate.mention}.")
            await self.pause()
            return

        await self._kill(game, candidate)
        text = f"🪢 Город повесил {candidate.mention}.{self._role_suffix(candidate)}"
        if candidate.role == Role.JESTER:
            game.jester_winner = candidate.user_id
            text += "\n\n🤡 <b>Самоубийца добился своего и победил!</b> А игра продолжается…"
        await self.send(game.chat_id, text)
        await self._offer_last_words(game, candidate, "🪢 Город решил вас повесить.")
        await self.pause()

    async def _punish_afk(self, game: Game) -> None:
        if config.AFK_LIMIT <= 0:
            return
        for p in game.alive():
            if p.user_id in game.votes:
                game.missed_votes[p.user_id] = 0
                continue
            game.missed_votes[p.user_id] = game.missed_votes.get(p.user_id, 0) + 1
            if game.missed_votes[p.user_id] >= config.AFK_LIMIT:
                await self._kill(game, p)
                await self.send(
                    game.chat_id,
                    f"💤 {p.mention} уснул(а) на {config.AFK_LIMIT} голосованиях подряд и выбывает из игры.{self._role_suffix(p)}",
                )
                await self.send(p.user_id, "💤 Вы выбыли из игры за бездействие.")

    def _vote_text(self, game: Game, final: bool = False) -> str:
        header = "🗳 <b>Итоги голосования</b>" if final else f"🗳 <b>Голосование!</b> Голосуйте в личке с ботом, {config.VOTE_TIME} сек."
        lines = []
        for voter_id, target in game.votes.items():
            voter = game.players[voter_id]
            if target == SKIP:
                lines.append(f"• {voter.mention} воздержался(ась)")
            else:
                lines.append(f"• {voter.mention} → {game.players[target].mention}")
        body = "\n".join(lines) or "<i>пока никто не проголосовал</i>"
        return f"{header}\n\n{body}"

    async def day_vote(self, game_id: str, round_: int, user_id: int, target: int, message: Message) -> str:
        game = self.by_id.get(game_id)
        if game is None or game.phase != Phase.VOTE or game.round != round_:
            raise GameError("Голосование уже закончилось.")
        voter = game.players.get(user_id)
        if voter is None or not voter.alive:
            raise GameError("Вы не можете голосовать.")
        if user_id in game.votes:
            return "Вы уже проголосовали."
        if target != SKIP and (target not in game.players or not game.players[target].alive or target == user_id):
            return "Нельзя голосовать за этого игрока."
        game.votes[user_id] = target
        if target == SKIP:
            await self.edit(user_id, message.message_id, f"{_prompt(message)}\n\n🤷 Вы воздержались.")
        else:
            await self.edit(user_id, message.message_id,
                            f"{_prompt(message)}\n\n✅ Вы голосуете против {game.players[target].mention}")
        if game.vote_message_id:
            await self.edit(game.chat_id, game.vote_message_id, self._vote_text(game), go_to_bot_keyboard("🗳 Голосовать"))
        self._check_phase_done(game)
        return "Голос принят"

    async def confirm_vote(self, game_id: str, round_: int, user_id: int, yes: bool) -> str:
        game = self.by_id.get(game_id)
        if game is None or game.phase != Phase.CONFIRM or game.round != round_:
            raise GameError("Голосование уже закончилось.")
        voter = game.players.get(user_id)
        if voter is None or not voter.alive:
            raise GameError("Голосуют только живые игроки.")
        if user_id == game.candidate:
            raise GameError("Обвиняемый не голосует 🙂")
        game.confirm[user_id] = yes
        yes_n = sum(1 for v in game.confirm.values() if v)
        no_n = len(game.confirm) - yes_n
        if game.confirm_message_id:
            await self.edit(game.chat_id, game.confirm_message_id, markup=confirm_keyboard(f"c:{game.id}:{game.round}", yes_n, no_n))
        self._check_phase_done(game)
        return "👍 Вешать" if yes else "👎 Помиловать"

    # ================================================================ общие механики

    def _check_phase_done(self, game: Game) -> None:
        if game.phase == Phase.NIGHT and night_complete(game):
            game.phase_done.set()
        elif game.phase == Phase.VOTE and all(uid in game.votes for uid in game.alive_ids()):
            game.phase_done.set()
        elif game.phase == Phase.CONFIRM:
            voters = [uid for uid in game.alive_ids() if uid != game.candidate]
            if all(uid in game.confirm for uid in voters):
                game.phase_done.set()

    def _role_suffix(self, p: Player) -> str:
        return f" Он(а) был(а) — <b>{role_title(p.role)}</b>." if config.REVEAL_ROLES and p.role else ""

    async def _kill(self, game: Game, p: Player) -> None:
        if not p.alive:
            return
        p.alive = False
        if p.role == Role.COMMISSAR:
            for sergeant in game.by_role(Role.SERGEANT):
                sergeant.role = Role.COMMISSAR
                await self.send(sergeant.user_id, "👮➡️🕵️ Комиссар погиб. Теперь <b>вы — Комиссар</b>! Со следующей ночи вы проверяете и стреляете.")
                await self.send(game.chat_id, "👮 Сержант принял дела погибшего комиссара.")
        if p.is_mafia:
            for m in game.mafia():
                await self.send(m.user_id, f"🕯 Семья потеряла {p.mention} ({role_title(p.role)}).")

    async def _offer_last_words(self, game: Game, p: Player, reason: str) -> None:
        game.last_words[p.user_id] = time.monotonic() + config.LAST_WORDS_TIME
        await self.send(
            p.user_id,
            f"{reason}\n\n💬 У вас {config.LAST_WORDS_TIME} сек. на последнее слово — напишите одно сообщение, я передам его в чат.",
        )

    async def private_text(self, user: User, text: str) -> Optional[str]:
        """Текст в личке: последнее слово или чат мафии. Возвращает ответ пользователю (или None)."""
        game = self.by_user.get(user.id)
        if game is None or game.phase in (Phase.LOBBY, Phase.FINISHED):
            return None
        player = game.players[user.id]
        deadline = game.last_words.get(user.id)
        if deadline is not None:
            del game.last_words[user.id]
            if time.monotonic() <= deadline:
                await self.send(game.chat_id, f"💬 <b>Последнее слово</b> {player.mention}:\n«{html.escape(text[:1000])}»")
                return "📨 Ваше последнее слово передано в чат."
            return "⌛ Время на последнее слово вышло."
        if not player.alive:
            return "👻 Мёртвые молчат."
        if player.is_mafia and game.phase in (Phase.NIGHT, Phase.RESOLVING):
            others = [m for m in game.mafia() if m.user_id != user.id]
            for m in others:
                await self.send(m.user_id, f"🤵 {player.mention}: {html.escape(text[:1000])}")
            return None if others else "Вы остались один(одна) в семье."
        if player.is_mafia:
            return "🤫 Переписываться с семьёй можно только ночью."
        return None

    def should_delete(self, chat_id: int, user_id: int) -> bool:
        """Удалять ли сообщение в групповом чате: мёртвые молчат, ночью молчат все игроки."""
        game = self.by_chat.get(chat_id)
        if game is None or game.phase in (Phase.LOBBY, Phase.FINISHED):
            return False
        player = game.players.get(user_id)
        if player is None:
            return False
        return not player.alive or game.phase in (Phase.NIGHT, Phase.RESOLVING)

    # ================================================================ итоги

    async def _finish(self, game: Game, outcome: Outcome) -> None:
        await self.pause()
        lines = [f"🏁 <b>Игра окончена!</b>\n\n{outcome.title}", ""]
        winners, losers = [], []
        rows = []
        for p in sorted(game.players.values(), key=lambda x: x.number):
            won = is_winner(p, outcome, game.jester_winner)
            status = "❤️" if p.alive else "💀"
            line = f"{status} {p.mention} — {role_title(p.role)}"
            (winners if won else losers).append(line)
            rows.append((p.user_id, p.name, p.role.value, won, p.alive))
        if winners:
            lines += ["🏆 <b>Победители:</b>", *winners, ""]
        if losers:
            lines += ["😵 <b>Проигравшие:</b>", *losers, ""]
        minutes = int((time.time() - game.started_at) // 60)
        lines.append(f"⏱ Игра длилась {minutes} мин, {game.round} ноч.")
        lines.append("Новая игра: /game · Статистика: /stats · Топ чата: /top")
        await self.send(game.chat_id, "\n".join(lines))
        try:
            await db.save_game(game.id, game.chat_id, rows)
        except Exception:
            logger.exception("Failed to save stats for game %s", game.id)


manager = GameManager()
