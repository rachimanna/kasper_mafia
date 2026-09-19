import random
import pytest

from bot.game.models import SKIP, Game, Player
from bot.game.roles import *  # noqa
from bot.game.rules import (
    allowed_targets, build_roles, check_winner, night_complete, resolve_night, tally_day_votes,
)


def make_game(roles):
    g = Game(id="g", chat_id=-1, chat_title="t", creator_id=1)
    for i, r in enumerate(roles, start=1):
        g.players[i] = Player(user_id=i, name=f"P{i}", number=i, role=r)
    return g


def choose(g, actor, action, target):
    g.night.choices[(actor, action)] = target


@pytest.mark.parametrize("n", range(3, 31))
def test_build_roles_counts(n):
    roles = build_roles(n)
    assert len(roles) == n
    mafia = sum(r in MAFIA_TEAM for r in roles)
    assert 1 <= mafia < n / 2
    assert roles.count(Role.DON) == 1
    if n >= 4:
        assert Role.COMMISSAR in roles
    # Сержант только при комиссаре, каждая спецроль максимум одна
    for r in (Role.COMMISSAR, Role.DOCTOR, Role.LOVER, Role.HOBO, Role.MANIAC, Role.SERGEANT, Role.JESTER, Role.LAWYER):
        assert roles.count(r) <= 1


def test_mafia_kill_and_doctor_save():
    g = make_game([Role.DON, Role.MAFIA, Role.DOCTOR, Role.CIVILIAN, Role.CIVILIAN])
    choose(g, 1, ACTION_KILL, 4); choose(g, 2, ACTION_KILL, 4); choose(g, 3, ACTION_HEAL, 4)
    r = resolve_night(g, random.Random(1))
    assert r.deaths == [] and r.saved == [4]
    choose(g, 3, ACTION_HEAL, 5)
    r = resolve_night(g, random.Random(1))
    assert r.deaths == [4]


def test_don_breaks_tie():
    g = make_game([Role.DON, Role.MAFIA, Role.CIVILIAN, Role.CIVILIAN])
    choose(g, 1, ACTION_KILL, 3); choose(g, 2, ACTION_KILL, 4)
    for seed in range(20):
        assert resolve_night(g, random.Random(seed)).deaths == [3]


def test_lover_blocks_and_hobo_sees():
    g = make_game([Role.DON, Role.LOVER, Role.HOBO, Role.CIVILIAN, Role.DOCTOR])
    choose(g, 2, ACTION_LOVE, 1)        # любовница блокирует дона
    choose(g, 1, ACTION_KILL, 4)
    choose(g, 3, ACTION_HOBO, 4)
    choose(g, 5, ACTION_HEAL, 4)
    r = resolve_night(g, random.Random(0))
    assert r.deaths == [] and 1 in r.blocked
    hobo_msgs = " ".join(r.private[3])
    assert "P5" in hobo_msgs and "P1" not in hobo_msgs  # видел доктора, дона — нет (он заблокирован)


def test_commissar_check_lawyer_and_sergeant():
    g = make_game([Role.DON, Role.LAWYER, Role.MAFIA, Role.COMMISSAR, Role.SERGEANT, Role.CIVILIAN])
    choose(g, 4, ACTION_COMMISSAR, 3); g.night.commissar_mode = "check"
    r = resolve_night(g, random.Random(0))
    assert "мафия" in r.private[4][0] and "мафия" in r.private[5][0]
    choose(g, 2, ACTION_LAWYER, 3)
    r = resolve_night(g, random.Random(0))
    assert "не мафия" in r.private[4][0]


def test_commissar_shoot_and_maniac():
    g = make_game([Role.DON, Role.COMMISSAR, Role.MANIAC, Role.CIVILIAN, Role.CIVILIAN])
    g.night.commissar_mode = "shoot"; choose(g, 2, ACTION_COMMISSAR, 1)
    choose(g, 3, ACTION_MANIAC, 4)
    choose(g, 1, ACTION_KILL, 5)
    r = resolve_night(g, random.Random(0))
    assert sorted(r.deaths) == [1, 4, 5]


def test_don_check():
    g = make_game([Role.DON, Role.COMMISSAR, Role.CIVILIAN, Role.CIVILIAN])
    choose(g, 1, ACTION_DON_CHECK, 2)
    assert "комиссар</b>" in resolve_night(g, random.Random(0)).private[1][0]


def test_allowed_targets_doctor_rules():
    g = make_game([Role.DON, Role.DOCTOR, Role.CIVILIAN, Role.CIVILIAN])
    doc = g.players[2]
    g.doctor_last = 3; g.doctor_self_used = True
    ids = [p.user_id for p in allowed_targets(g, doc, ACTION_HEAL)]
    assert 3 not in ids and 2 not in ids and 1 in ids
    assert all(not p.is_mafia for p in allowed_targets(g, g.players[1], ACTION_KILL))


def test_night_complete():
    g = make_game([Role.DON, Role.DOCTOR, Role.CIVILIAN])
    assert not night_complete(g)
    choose(g, 1, ACTION_KILL, 3); choose(g, 1, ACTION_DON_CHECK, SKIP)
    assert not night_complete(g)
    choose(g, 2, ACTION_HEAL, 3)
    assert night_complete(g)


def test_day_votes():
    assert tally_day_votes({1: 3, 2: 3, 3: 1}) == 3
    assert tally_day_votes({1: 3, 2: 1}) is None            # ничья
    assert tally_day_votes({1: 3, 2: SKIP}) is None         # воздержавшихся не меньше
    assert tally_day_votes({1: SKIP}) is None
    assert tally_day_votes({}) is None


def test_winners():
    g = make_game([Role.DON, Role.CIVILIAN, Role.CIVILIAN])
    assert check_winner(g) is None
    g.players[2].alive = False
    assert check_winner(g).team == Team.MAFIA
    g = make_game([Role.DON, Role.CIVILIAN, Role.MANIAC])
    g.players[2].alive = False
    assert check_winner(g).team == Team.MANIAC
    g = make_game([Role.DON, Role.CIVILIAN, Role.CIVILIAN])
    g.players[1].alive = False
    assert check_winner(g).team == Team.TOWN
    for p in g.players.values():
        p.alive = False
    assert check_winner(g).team is None
