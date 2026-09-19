"""Чистая игровая логика без Telegram: раздача ролей, ночь, голосование, условия победы."""
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from bot.game.models import SKIP, Game, NightActions, Player
from bot.game.roles import (
    ACTION_COMMISSAR, ACTION_DON_CHECK, ACTION_HEAL, ACTION_HOBO, ACTION_KILL, ACTION_LAWYER,
    ACTION_LOVE, ACTION_MANIAC, MAFIA_KILLERS, MAFIA_TEAM, ROLE_ACTIONS, Role, Team,
)


# ---------------------------------------------------------------- раздача ролей

def build_roles(n: int) -> List[Role]:
    """Состав ролей для n игроков (без перемешивания)."""
    if n < 3:
        raise ValueError("Нужно минимум 3 игрока")

    mafia_total = max(1, int(n / 3.5))
    roles: List[Role] = [Role.DON]
    if mafia_total >= 3:
        roles.append(Role.LAWYER)
    roles += [Role.MAFIA] * (mafia_total - len(roles))

    specials = [
        (4, Role.COMMISSAR),
        (5, Role.DOCTOR),
        (7, Role.LOVER),
        (8, Role.HOBO),
        (9, Role.MANIAC),
        (10, Role.SERGEANT),
        (12, Role.JESTER),
    ]
    roles += [role for min_players, role in specials if n >= min_players]
    roles += [Role.CIVILIAN] * (n - len(roles))
    assert len(roles) == n
    return roles


def assign_roles(players: List[Player], rng: random.Random) -> None:
    roles = build_roles(len(players))
    rng.shuffle(roles)
    for player, role in zip(players, roles):
        player.role = role


def actions_for(player: Player) -> Tuple[str, ...]:
    return ROLE_ACTIONS.get(player.role, ()) if player.alive and player.role else ()


# ---------------------------------------------------------------- допустимые цели

def allowed_targets(game: Game, actor: Player, action: str) -> List[Player]:
    alive = [p for p in game.alive()]
    others = [p for p in alive if p.user_id != actor.user_id]

    if action in (ACTION_KILL, ACTION_DON_CHECK):
        return [p for p in alive if not p.is_mafia]
    if action == ACTION_HEAL:
        return [
            p for p in alive
            if p.user_id != game.doctor_last and not (p.user_id == actor.user_id and game.doctor_self_used)
        ]
    if action == ACTION_LOVE:
        return [p for p in others if p.user_id != game.lover_last]
    if action in (ACTION_COMMISSAR, ACTION_LAWYER, ACTION_MANIAC, ACTION_HOBO):
        return others
    return []


def night_complete(game: Game) -> bool:
    """Все ли живые игроки с ночными ролями сделали выбор."""
    for player in game.alive():
        for action in actions_for(player):
            if game.night.choice(player.user_id, action) is None:
                return False
    return True


# ---------------------------------------------------------------- разрешение ночи

@dataclass
class NightResult:
    deaths: List[int] = field(default_factory=list)          # в порядке событий
    saved: List[int] = field(default_factory=list)           # кого спас доктор
    blocked: Set[int] = field(default_factory=set)           # к кому приходила любовница
    mafia_target: Optional[int] = None
    private: Dict[int, List[str]] = field(default_factory=dict)  # личные сообщения по итогам ночи

    def tell(self, user_id: int, text: str) -> None:
        self.private.setdefault(user_id, []).append(text)


def _pick_mafia_target(votes: Dict[int, int], don_id: Optional[int], rng: random.Random) -> Optional[int]:
    real = {voter: target for voter, target in votes.items() if target != SKIP}
    if not real:
        return None
    counts = Counter(real.values())
    best = max(counts.values())
    tied = sorted(t for t, c in counts.items() if c == best)
    if len(tied) == 1:
        return tied[0]
    if don_id is not None and real.get(don_id) in tied:
        return real[don_id]
    return rng.choice(tied)


def resolve_night(game: Game, rng: random.Random) -> NightResult:
    """Считает итоги ночи. Не меняет состояние игры — это делает менеджер."""
    a: NightActions = game.night
    players = game.players
    alive: Set[int] = set(game.alive_ids())
    result = NightResult()

    def actor(role: Role) -> Optional[Player]:
        found = game.by_role(role)
        return found[0] if found else None

    def target_of(p: Optional[Player], action: str) -> Optional[int]:
        if p is None or not p.alive:
            return None
        t = a.choice(p.user_id, action)
        return t if t not in (None, SKIP) and t in alive else None

    # Кто куда ходил (для Бомжа): цель -> список посетителей
    visits: Dict[int, List[int]] = {}

    def visit(visitor: Player, target: Optional[int]) -> None:
        if target is not None and target != visitor.user_id:
            visits.setdefault(target, []).append(visitor.user_id)

    # 1. Любовница блокирует ход цели
    lover = actor(Role.LOVER)
    lover_target = target_of(lover, ACTION_LOVE)
    if lover and lover_target:
        result.blocked.add(lover_target)
        visit(lover, lover_target)
        target_player = players[lover_target]
        if actions_for(target_player):
            result.tell(lover_target, "💃 Этой ночью к вам заглянула Любовница — вы так никуда и не пошли.")
        else:
            result.tell(lover_target, "💃 Этой ночью к вам заглянула Любовница. Прекрасная ночь!")

    def active(p: Optional[Player]) -> bool:
        return p is not None and p.alive and p.user_id not in result.blocked

    kills: Dict[int, List[str]] = {}

    # 2. Мафия
    don = actor(Role.DON)
    mafia_votes = {
        p.user_id: a.choice(p.user_id, ACTION_KILL)
        for p in game.alive()
        if p.role in MAFIA_KILLERS and active(p) and a.choice(p.user_id, ACTION_KILL) is not None
    }
    mafia_votes = {v: t for v, t in mafia_votes.items() if t == SKIP or t in alive}
    mafia_target = _pick_mafia_target(mafia_votes, don.user_id if don else None, rng)
    if mafia_target is not None:
        result.mafia_target = mafia_target
        kills.setdefault(mafia_target, []).append("mafia")
        # «Исполнитель» для свидетеля — Дон, если голосовал за эту цель, иначе первый проголосовавший.
        executors = [v for v, t in mafia_votes.items() if t == mafia_target]
        executor = don.user_id if don and don.user_id in executors else executors[0]
        visit(players[executor], mafia_target)

    # 3. Маньяк
    maniac = actor(Role.MANIAC)
    if active(maniac):
        t = target_of(maniac, ACTION_MANIAC)
        if t:
            kills.setdefault(t, []).append("maniac")
            visit(maniac, t)

    # 4. Комиссар
    commissar = actor(Role.COMMISSAR)
    lawyer = actor(Role.LAWYER)
    protected = target_of(lawyer, ACTION_LAWYER) if active(lawyer) else None
    if active(lawyer) and protected:
        visit(lawyer, protected)

    if active(commissar):
        t = target_of(commissar, ACTION_COMMISSAR)
        if t:
            visit(commissar, t)
            if a.commissar_mode == "shoot":
                kills.setdefault(t, []).append("commissar")
            else:
                target_player = players[t]
                is_mafia = target_player.is_mafia and t != protected
                verdict = "🤵 <b>мафия</b>!" if is_mafia else "😇 не мафия."
                text = f"🕵️ Проверка: {target_player.mention} — {verdict}"
                result.tell(commissar.user_id, text)
                for sergeant in game.by_role(Role.SERGEANT):
                    result.tell(sergeant.user_id, f"📨 Комиссар сообщает: {target_player.mention} — {verdict}")
    elif commissar and commissar.user_id in result.blocked:
        for sergeant in game.by_role(Role.SERGEANT):
            result.tell(sergeant.user_id, "📨 Этой ночью комиссар так и не вышел на связь.")

    # 5. Проверка Дона
    if active(don):
        t = target_of(don, ACTION_DON_CHECK)
        if t:
            if t != result.mafia_target:
                visit(don, t)
            is_com = players[t].role == Role.COMMISSAR
            verdict = "🕵️ <b>комиссар</b>!" if is_com else "не комиссар."
            result.tell(don.user_id, f"🎩 Проверка: {players[t].mention} — {verdict}")

    # 6. Доктор
    doctor = actor(Role.DOCTOR)
    healed = target_of(doctor, ACTION_HEAL) if active(doctor) else None
    if doctor and healed:
        if healed != doctor.user_id:
            visit(doctor, healed)
        if healed in kills:
            result.saved.append(healed)
            result.tell(healed, "🩺 Этой ночью на вас напали, но Доктор успел вас спасти!")
            if healed != doctor.user_id:
                result.tell(doctor.user_id, f"🩺 Вы спасли {players[healed].mention} от смерти!")
            del kills[healed]

    result.deaths = [uid for uid in kills if uid in alive]

    # 7. Бомж
    hobo = actor(Role.HOBO)
    if active(hobo):
        t = target_of(hobo, ACTION_HOBO)
        if t:
            guests = [g for g in visits.get(t, []) if g != hobo.user_id]
            if guests:
                names = ", ".join(players[g].mention for g in dict.fromkeys(guests))
                result.tell(hobo.user_id, f"🧥 У дома {players[t].mention} вы видели: {names}.")
            else:
                result.tell(hobo.user_id, f"🧥 К {players[t].mention} этой ночью никто не приходил.")
            if t in result.deaths:
                result.tell(hobo.user_id, f"🧥 А утром {players[t].mention} нашли мёртвым…")

    return result


# ---------------------------------------------------------------- дневное голосование

def tally_day_votes(votes: Dict[int, int]) -> Optional[int]:
    """Кандидат на казнь: строго больше всех голосов и больше, чем воздержавшихся. Иначе None."""
    real = Counter(t for t in votes.values() if t != SKIP)
    if not real:
        return None
    best = max(real.values())
    leaders = [t for t, c in real.items() if c == best]
    abstained = sum(1 for t in votes.values() if t == SKIP)
    if len(leaders) != 1 or abstained >= best:
        return None
    return leaders[0]


# ---------------------------------------------------------------- победа

@dataclass
class Outcome:
    team: Optional[Team]  # None = ничья
    title: str


def check_winner(game: Game) -> Optional[Outcome]:
    alive = game.alive()
    if not alive:
        return Outcome(None, "🤝 Ничья — в городе не осталось никого.")

    mafia = [p for p in alive if p.role in MAFIA_TEAM]
    maniac = [p for p in alive if p.role == Role.MANIAC]
    others = len(alive) - len(mafia)

    if maniac and len(alive) <= 2:
        return Outcome(Team.MANIAC, "🪓 Победил Маньяк! Город утонул в крови.")
    if not mafia and not maniac:
        return Outcome(Team.TOWN, "🏘 Победили мирные жители! Город очищен от преступности.")
    if mafia and not maniac and len(mafia) >= others:
        return Outcome(Team.MAFIA, "🤵 Победила мафия! Теперь город принадлежит семье.")
    return None


def is_winner(player: Player, outcome: Outcome, jester_winner: Optional[int]) -> bool:
    if player.role == Role.JESTER:
        return jester_winner == player.user_id
    return outcome.team is not None and player.team == outcome.team
