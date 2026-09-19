"""
Симуляция полных игр: боты-игроки сами присоединяются, жмут ночные кнопки,
голосуют, пишут в чат мафии и последние слова. Запуск: python -m tests.simulate
"""
import asyncio
import logging
import os
import random
import re
import sys
import time

PORT = 18081
os.environ.update(
    BOT_TOKEN="123:TEST", API_SERVER=f"http://127.0.0.1:{PORT}", DB_PATH=":memory:",
    WEB_SERVER_ENABLED="false", MIN_PLAYERS="4",
)

from aiogram.types import Update  # noqa: E402

from bot.config import config  # noqa: E402
# Ускоренные тайминги для симуляции (в обход минимальных значений конфига)
for key, value in dict(REGISTRATION_TIME=30, NIGHT_TIME=2, DAY_TIME=0, DAY_TIME_PER_PLAYER=0, VOTE_TIME=2,
                       CONFIRM_TIME=2, LAST_WORDS_TIME=5, PHASE_PAUSE=0, REGISTRATION_EXTEND=5).items():
    setattr(config, key, value)
from bot.db import db  # noqa: E402
from bot.game.manager import manager  # noqa: E402
from bot.main import build_dispatcher, create_bot  # noqa: E402
from tests.fake_telegram import FakeTelegram  # noqa: E402

GROUP = -1001
errors = []


class ErrorCatcher(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            errors.append(self.format(record))


logging.basicConfig(level=logging.WARNING)
logging.getLogger().addHandler(ErrorCatcher())

update_ids = iter(range(1, 10**9))


def user(uid):
    return {"id": uid, "is_bot": False, "first_name": f"Игрок{uid}", "username": f"u{uid}"}


def message_update(chat_id, uid, text):
    chat = {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"}
    if chat_id < 0:
        chat["title"] = "Test Group"
    else:
        chat["first_name"] = f"Игрок{uid}"
    entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else None
    msg = {"message_id": next(update_ids), "date": int(time.time()), "chat": chat, "from": user(uid), "text": text}
    if entities:
        msg["entities"] = entities
    return Update.model_validate({"update_id": next(update_ids), "message": msg})


def callback_update(tg, sent, uid, data):
    return Update.model_validate({
        "update_id": next(update_ids),
        "callback_query": {
            "id": str(next(update_ids)), "from": user(uid), "chat_instance": "x", "data": data,
            "message": tg.msg_json(sent),
        },
    })


def buttons(sent):
    if not sent.markup:
        return []
    return [b for row in sent.markup.get("inline_keyboard", []) for b in row]


async def play_one(n_players: int, seed: int, tg: FakeTelegram, bot, dp) -> str:
    rng = random.Random(seed)
    manager.rng.seed(seed)
    users = [1000 * seed + i for i in range(1, n_players + 1)]
    feed = lambda upd: dp.feed_update(bot, upd)  # noqa: E731

    await feed(message_update(GROUP, users[0], "/game"))
    lobby = next(s for s in reversed(tg.by_chat[GROUP]) if "Набор в игру" in s.text)
    join_url = buttons(lobby)[0]["url"]
    payload = join_url.split("start=")[1]
    for uid in users:
        await feed(message_update(uid, uid, f"/start {payload}"))
    # попытка повторного входа и выхода/возврата
    await feed(message_update(users[-1], users[-1], "/leave"))
    await feed(message_update(users[-1], users[-1], f"/start {payload}"))
    game = manager.by_chat[GROUP]
    assert len(game.players) == n_players, len(game.players)
    if n_players < 20:
        await feed(message_update(GROUP, users[0], "/begin"))

    clicked = set()
    deadline = time.monotonic() + 600
    while GROUP in manager.by_chat and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        # приватные кнопки
        for uid in users:
            for s in list(tg.by_chat.get(uid, [])):
                btns = [b for b in buttons(s) if "callback_data" in b]
                key = (s.chat_id, s.message_id, s.text)
                if not btns or key in clicked:
                    continue
                if rng.random() < 0.15:  # иногда игрок тупит и не жмёт
                    clicked.add(key)
                    continue
                non_skip = [b for b in btns if not b["callback_data"].endswith((":0", ":skip"))]
                b = rng.choice(non_skip if non_skip and rng.random() < 0.9 else btns)
                clicked.add(key)
                await feed(callback_update(tg, s, uid, b["callback_data"]))
            # последнее слово / чат мафии
            for s in list(tg.by_chat.get(uid, []))[-3:]:
                key = ("words", s.chat_id, s.message_id)
                if key in clicked:
                    continue
                if "последнее слово" in s.text or "Ваша семья" in s.text:
                    clicked.add(key)
                    await feed(message_update(uid, uid, "Я был невиновен! <b>тег</b> & всё"))
        # голосование «вешать?» в группе
        for s in list(tg.by_chat.get(GROUP, []))[-3:]:
            btns = [b for b in buttons(s) if b.get("callback_data", "").startswith("c:")]
            if btns:
                for uid in users:
                    key = ("confirm", s.message_id, uid)
                    if key not in clicked and rng.random() < 0.5:
                        clicked.add(key)
                        await feed(callback_update(tg, s, uid, rng.choice(btns)["callback_data"]))
        # случайная болтовня в группе (ночью и от мёртвых должна удаляться)
        if rng.random() < 0.05:
            await feed(message_update(GROUP, rng.choice(users), "я точно мирный"))

    finals = [s.text for s in tg.by_chat[GROUP] if "Игра окончена" in s.text]
    assert finals, "game did not finish"
    return finals[-1]


async def main():
    tg = FakeTelegram()
    runner = await tg.start(PORT)
    bot = create_bot()
    await db.init()
    config.BOT_USERNAME = (await bot.get_me()).username
    manager.setup(bot)
    dp = build_dispatcher()

    sizes = [int(x) for x in sys.argv[1:]] or [4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20]
    outcomes = {}
    for i, n in enumerate(sizes):
        final = await play_one(n, seed=i + 1, tg=tg, bot=bot, dp=dp)
        title = final.split("\n")[2]
        outcomes[n] = title
        print(f"{n:>2} игроков: {re.sub('<.*?>', '', title)}")

    games, wins, survived, roles = await db.user_stats(1001)
    print("stats for 1001:", games, wins, survived, roles)
    print("deleted messages:", len(tg.deleted), "| callback answers:", len(tg.callback_answers))
    alerts = [a.get("text") for a in tg.callback_answers if a.get("show_alert") in ("true", "True", True)]
    print("alerts sample:", sorted(set(alerts))[:8])
    await bot.session.close()
    await db.close()
    await runner.cleanup()
    if errors:
        print("ERRORS:\n" + "\n".join(errors[:10]))
        sys.exit(1)
    print("ALL GAMES OK")


if __name__ == "__main__":
    asyncio.run(main())
