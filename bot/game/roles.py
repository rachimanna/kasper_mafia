from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet


class Team(str, Enum):
    TOWN = "town"
    MAFIA = "mafia"
    MANIAC = "maniac"
    JESTER = "jester"


TEAM_TITLES = {
    Team.TOWN: "🏘 Мирные жители",
    Team.MAFIA: "🤵 Мафия",
    Team.MANIAC: "🪓 Маньяк",
    Team.JESTER: "🤡 Самоубийца",
}


class Role(str, Enum):
    CIVILIAN = "civilian"
    DON = "don"
    MAFIA = "mafia"
    LAWYER = "lawyer"
    COMMISSAR = "commissar"
    SERGEANT = "sergeant"
    DOCTOR = "doctor"
    LOVER = "lover"
    HOBO = "hobo"
    MANIAC = "maniac"
    JESTER = "jester"


@dataclass(frozen=True)
class RoleInfo:
    name: str
    emoji: str
    team: Team
    description: str

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}"


ROLES: Dict[Role, RoleInfo] = {
    Role.CIVILIAN: RoleInfo(
        "Мирный житель", "👨‍🌾", Team.TOWN,
        "Ночью спит. Днём ищет мафию в обсуждении и голосует. Сила города — в его голосах.",
    ),
    Role.DON: RoleInfo(
        "Дон", "🎩", Team.MAFIA,
        "Глава мафии. Ночью голосует за жертву вместе с мафией (при ничьей решает его голос) "
        "и может проверить одного игрока — не комиссар ли он.",
    ),
    Role.MAFIA: RoleInfo(
        "Мафия", "🤵", Team.MAFIA,
        "Ночью вместе с семьёй выбирает жертву. Может переписываться с сообщниками через бота.",
    ),
    Role.LAWYER: RoleInfo(
        "Адвокат", "💼", Team.MAFIA,
        "Играет за мафию. Ночью берёт под защиту игрока: если комиссар его проверит, тот окажется «мирным».",
    ),
    Role.COMMISSAR: RoleInfo(
        "Комиссар", "🕵️", Team.TOWN,
        "Главный защитник города. Каждую ночь либо проверяет игрока (мафия или нет), либо стреляет в него.",
    ),
    Role.SERGEANT: RoleInfo(
        "Сержант", "👮", Team.TOWN,
        "Помощник комиссара: узнаёт результаты его проверок. Если комиссар погибнет — займёт его место.",
    ),
    Role.DOCTOR: RoleInfo(
        "Доктор", "🩺", Team.TOWN,
        "Ночью лечит одного игрока и спасает его от смерти. Нельзя лечить одного и того же две ночи подряд, "
        "себя — только один раз за игру.",
    ),
    Role.LOVER: RoleInfo(
        "Любовница", "💃", Team.TOWN,
        "Ночью приходит в гости к игроку и отвлекает его: этой ночью он не сможет сделать свой ход. "
        "К одному и тому же нельзя ходить две ночи подряд.",
    ),
    Role.HOBO: RoleInfo(
        "Бомж", "🧥", Team.TOWN,
        "Ночью ходит за бутылками к дому игрока и видит всех, кто к нему заходил. Свидетель, которого никто не замечает.",
    ),
    Role.MANIAC: RoleInfo(
        "Маньяк", "🪓", Team.MANIAC,
        "Играет сам за себя. Каждую ночь убивает одного игрока. Побеждает, если останется один на один с кем угодно.",
    ),
    Role.JESTER: RoleInfo(
        "Самоубийца", "🤡", Team.JESTER,
        "Хочет, чтобы город его повесил. Если днём его казнят — он побеждает (игра продолжается без него).",
    ),
}

MAFIA_TEAM: FrozenSet[Role] = frozenset({Role.DON, Role.MAFIA, Role.LAWYER})
MAFIA_KILLERS: FrozenSet[Role] = frozenset({Role.DON, Role.MAFIA})

# Ночные действия и какие роли их выполняют.
ACTION_KILL = "kill"          # голос мафии
ACTION_DON_CHECK = "dcheck"   # проверка Дона
ACTION_COMMISSAR = "com"      # проверка или выстрел комиссара
ACTION_HEAL = "heal"
ACTION_LOVE = "love"
ACTION_LAWYER = "lawyer"
ACTION_MANIAC = "maniac"
ACTION_HOBO = "hobo"

ROLE_ACTIONS = {
    Role.DON: (ACTION_KILL, ACTION_DON_CHECK),
    Role.MAFIA: (ACTION_KILL,),
    Role.LAWYER: (ACTION_LAWYER,),
    Role.COMMISSAR: (ACTION_COMMISSAR,),
    Role.DOCTOR: (ACTION_HEAL,),
    Role.LOVER: (ACTION_LOVE,),
    Role.MANIAC: (ACTION_MANIAC,),
    Role.HOBO: (ACTION_HOBO,),
}


def role_title(role: Role) -> str:
    return ROLES[role].title


def team_of(role: Role) -> Team:
    return ROLES[role].team
