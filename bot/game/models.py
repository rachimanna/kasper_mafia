import asyncio
import html
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from bot.game.roles import MAFIA_TEAM, Role, Team, team_of

SKIP = 0  # «пропустить ход» / «воздержаться»


class Phase(str, Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    RESOLVING = "resolving"
    DAY = "day"
    VOTE = "vote"
    CONFIRM = "confirm"
    FINISHED = "finished"


@dataclass
class Player:
    user_id: int
    name: str
    number: int = 0
    role: Optional[Role] = None
    alive: bool = True

    @property
    def mention(self) -> str:
        return f'<a href="tg://user?id={self.user_id}">{html.escape(self.name)}</a>'

    @property
    def label(self) -> str:
        """Для кнопок: «3. Вася»."""
        return f"{self.number}. {self.name}"

    @property
    def is_mafia(self) -> bool:
        return self.role in MAFIA_TEAM

    @property
    def team(self) -> Optional[Team]:
        return team_of(self.role) if self.role else None


@dataclass
class NightActions:
    # (игрок, действие) -> цель (SKIP = пропустил)
    choices: Dict[Tuple[int, str], int] = field(default_factory=dict)
    commissar_mode: Optional[str] = None  # "check" | "shoot"
    announced: set = field(default_factory=set)  # какие действия уже анонсированы в чате

    def choice(self, actor: int, action: str) -> Optional[int]:
        return self.choices.get((actor, action))


@dataclass
class Game:
    id: str
    chat_id: int
    chat_title: str
    creator_id: int
    players: Dict[int, Player] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    round: int = 0

    # Лобби
    lobby_message_id: Optional[int] = None
    registration_deadline: float = 0.0
    start_now: asyncio.Event = field(default_factory=asyncio.Event)

    # Ночь
    night: NightActions = field(default_factory=NightActions)
    doctor_last: Optional[int] = None
    doctor_self_used: bool = False
    lover_last: Optional[int] = None
    prompts: List[Tuple[int, int]] = field(default_factory=list)  # (chat_id, message_id) ночных кнопок

    # День
    votes: Dict[int, int] = field(default_factory=dict)
    vote_message_id: Optional[int] = None
    candidate: Optional[int] = None
    confirm: Dict[int, bool] = field(default_factory=dict)
    confirm_message_id: Optional[int] = None

    phase_done: asyncio.Event = field(default_factory=asyncio.Event)
    last_words: Dict[int, float] = field(default_factory=dict)  # user_id -> дедлайн
    idle_rounds: int = 0
    missed_votes: Dict[int, int] = field(default_factory=dict)  # пропущенные дневные голосования подряд
    jester_winner: Optional[int] = None
    task: Optional[asyncio.Task] = None
    started_at: float = field(default_factory=time.time)

    # ---------- выборки ----------

    def alive(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def alive_ids(self) -> List[int]:
        return [p.user_id for p in self.players.values() if p.alive]

    def by_role(self, role: Role, alive_only: bool = True) -> List[Player]:
        return [p for p in self.players.values() if p.role == role and (p.alive or not alive_only)]

    def mafia(self, alive_only: bool = True) -> List[Player]:
        return [p for p in self.players.values() if p.is_mafia and (p.alive or not alive_only)]

    def player_by_number(self, number: int) -> Optional[Player]:
        return next((p for p in self.players.values() if p.number == number), None)
